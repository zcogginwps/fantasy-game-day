"""Fake leagues built from real players, for previewing the app without credentials.

Uses the actual Sleeper player dictionary and the actual NFL schedule, so the
output looks exactly like the real thing - only the league names and rosters are
invented.
"""

from . import schedule as schedule_module
from . import teams as teams_module
from . import sleeper as sleeper_client

LEAGUE_NAMES = [
    ("Dynasty Warriors", "sleeper", "Big Sexy"),
    ("Office League", "sleeper", "Trash Pandas"),
    ("The Money League", "espn", "Gridiron Gang"),
    ("College Buddies", "espn", "Kyle's Killers"),
]

STARTING_SLOTS = ["QB", "RB1", "RB2", "WR1", "WR2", "WR3", "TE", "FLEX", "K", "DEF"]
WANTED = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 1, "DEF": 1}


def _eligible_players(players, playing_teams):
    """Real, rostered-calibre players whose team plays on the target date."""
    pool = {position: [] for position in WANTED}
    for player_id, player in players.items():
        position = player.get("position")
        if position not in WANTED:
            continue
        team = player.get("team")
        if not team:
            continue
        if teams_module.normalize(team) not in playing_teams:
            continue
        if position == "DEF":
            # Team defenses carry no status or search rank in Sleeper's data.
            pool[position].append((0, player_id))
            continue
        if player.get("status") != "Active":
            continue
        # search_rank approximates fantasy relevance; low is better.
        rank = player.get("search_rank")
        if rank is None or rank > 400:
            continue
        pool[position].append((rank, player_id))

    for position in pool:
        pool[position].sort()
    return pool


def build_leagues(target_date, tz):
    """Four plausible leagues built from players in that day's games."""
    return _build(schedule_module.games_on(target_date, tz))


def build_leagues_for_week(season, week, tz):
    """Same, but drawing on every team playing anywhere in the week.

    Seeding from a single day would leave the week's other days empty, since a
    roster built from Thursday's two teams has nobody playing on Sunday.
    """
    games = []
    for _, day_games in schedule_module.games_in_week(season, week, tz):
        games.extend(day_games)
    return _build(games)


def _build(games):
    players = sleeper_client.get_players()
    playing = set()
    for game in games:
        playing.add(game.home)
        playing.add(game.away)

    pool = _eligible_players(players, playing)

    cursor = {position: 0 for position in WANTED}

    def take(position, count):
        chosen = []
        available = pool.get(position) or []
        for _ in range(count):
            if cursor[position] >= len(available):
                break
            chosen.append(available[cursor[position]][1])
            cursor[position] += 1
        return chosen

    def make_roster():
        # Order must line up with STARTING_SLOTS, FLEX included.
        picks = []
        for position, count in [("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1),
                                ("RB", 1), ("K", 1), ("DEF", 1)]:
            picks.extend(take(position, count))
        slots = {}
        for index, player_id in enumerate(picks):
            slots[player_id] = STARTING_SLOTS[index] if index < len(STARTING_SLOTS) else "BN"
        for player_id in take("RB", 1) + take("WR", 1):
            slots[player_id] = "BN"
        return slots

    leagues = []
    for name, platform, opponent_name in LEAGUE_NAMES:
        leagues.append({
            "platform": platform,
            "id_source": "sleeper",  # Demo rosters always use Sleeper ids.
            "league_id": "demo-%s" % name.lower().replace(" ", "-"),
            "league_name": name,
            "week": 1,
            "my_slots": make_roster(),
            "opponents": [{"name": opponent_name, "slots": make_roster()}],
            "players": {},
        })

    # Deliberately give one player two roles so the yellow "conflict" state shows.
    donor = leagues[0]["my_slots"]
    if donor:
        shared = sorted(donor.keys())[0]
        leagues[2]["opponents"][0]["slots"][shared] = "FLEX"

    return leagues, players
