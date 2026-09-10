"""ESPN fantasy football client.

ESPN has no public fantasy API. We use the same endpoint their web app calls,
authenticated with the two cookies a logged-in browser holds: `espn_s2` and
`SWID`. Private leagues return 401 without them.
"""

import urllib.parse

from . import teams
from .webreq import FetchError, get_json

LEAGUE_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
FAN_BASE = "https://fan.api.espn.com/apis/v2/fans"

# ESPN identifies everything by integer id, so these tables are the decoder ring.
PRO_TEAMS = {
    0: None, 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB",
    28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

POSITIONS = {
    1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 7: "P", 9: "DT", 10: "DE",
    11: "LB", 12: "CB", 13: "S", 14: "DB", 16: "DEF",
}

# Slot ids as they appear in a lineup. Bench/IR are what we treat as non-starting.
LINEUP_SLOTS = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE",
    7: "OP", 8: "DT", 9: "DE", 10: "LB", 11: "DL", 12: "CB", 13: "S",
    14: "DB", 15: "DP", 16: "DEF", 17: "K", 18: "P", 19: "HC", 20: "BN",
    21: "IR", 23: "FLEX", 24: "EDR",
}

BENCH_SLOTS = (20, 21)

INJURY_LABELS = {
    "ACTIVE": "",
    "NORMAL": "",
    "PROBABLE": "Probable",
    "QUESTIONABLE": "Questionable",
    "DOUBTFUL": "Doubtful",
    "OUT": "Out",
    "INJURY_RESERVE": "IR",
    "SUSPENSION": "Suspended",
    "DAY_TO_DAY": "Day-to-Day",
    "FOUR_GAME_SUSPENSION": "Suspended",
    "PRACTICE_SQUAD": "Practice Squad",
}


def _cookies(config):
    swid = (config.get("swid") or "").strip()
    # ESPN stores SWID wrapped in braces; accept it either way and re-add them.
    if swid and not swid.startswith("{"):
        swid = "{%s}" % swid.strip("{}")
    return {"espn_s2": (config.get("espn_s2") or "").strip(), "SWID": swid}, swid


def discover_leagues(config, season):
    """Ask ESPN which fantasy football leagues this account belongs to.

    Convenience only - if it fails for any reason the user can list league ids
    manually in the config instead.
    """
    cookies, swid = _cookies(config)
    if not swid:
        return []

    # SWID is wrapped in braces, which are not legal in a URL path and make
    # ESPN answer 400 unless they are percent-encoded.
    url = "%s/%s?featureFlags=challengeEntries&showAirings=false&source=ESPNFantasyApp&lang=en&section=fantasy" % (
        FAN_BASE,
        urllib.parse.quote(swid, safe=""),
    )
    try:
        payload = get_json(url, cookies=cookies)
    except FetchError:
        return []

    found = []
    for preference in payload.get("preferences") or []:
        entry = ((preference.get("metaData") or {}).get("entry")) or {}
        # abbrev "FFL" is fantasy football; skip basketball, baseball, etc.
        if entry.get("abbrev") and entry.get("abbrev") != "FFL":
            continue
        for group in entry.get("groups") or []:
            group_id = group.get("groupId")
            if group_id and str(group_id) not in found:
                found.append(str(group_id))
    return found


def fetch_league(league_id, season, config):
    """Raw league payload with rosters, matchups and team metadata."""
    cookies, _ = _cookies(config)
    url = (
        "%s/%s/segments/0/leagues/%s"
        "?view=mRoster&view=mMatchup&view=mMatchupScore&view=mTeam&view=mSettings"
        % (LEAGUE_BASE, season, league_id)
    )
    return get_json(url, cookies=cookies)


def _team_name(team):
    name = team.get("name")
    if name:
        return name.strip()
    combined = " ".join(
        filter(None, [team.get("location"), team.get("nickname")])
    ).strip()
    return combined or "Team %s" % team.get("id")


def _slot_label(slot_id):
    return LINEUP_SLOTS.get(slot_id, "BN")


def _roster_entries(team):
    """Yield (espn_player_id, slot_label, raw_player, applied_points) for one team."""
    roster = team.get("roster") or {}
    for entry in roster.get("entries") or []:
        pool = entry.get("playerPoolEntry") or {}
        player = pool.get("player") or {}
        player_id = entry.get("playerId") or player.get("id")
        if player_id is None:
            continue
        # appliedStatTotal is this league's scoring applied to the current
        # period. The player's own stats array also carries projections
        # (statSourceId 1), which are not what we want to show.
        yield (str(player_id), _slot_label(entry.get("lineupSlotId")), player,
               pool.get("appliedStatTotal"))


def player_record(player):
    """Normalise an ESPN player object into the shared shape."""
    raw_status = (player.get("injuryStatus") or "").upper()
    return {
        "name": player.get("fullName") or "Unknown player",
        "position": POSITIONS.get(player.get("defaultPositionId"), ""),
        "team": teams.normalize(PRO_TEAMS.get(player.get("proTeamId"))),
        "injury_status": INJURY_LABELS.get(raw_status, raw_status.title()),
        "injury_body_part": "",
        "espn_id": str(player.get("id")) if player.get("id") is not None else None,
        "source": "espn",
    }


def load_league(league_id, season, week, config):
    """Pull everything needed from one ESPN league.

    Returns the same shape as the Sleeper loader, plus a `players` map of ESPN
    player data so callers can fall back on it when Sleeper has no match.
    """
    payload = fetch_league(league_id, season, config)

    cookies, swid = _cookies(config)
    all_teams = payload.get("teams") or []

    my_team = None
    for team in all_teams:
        owners = [str(o) for o in (team.get("owners") or [])]
        if swid and swid in owners:
            my_team = team
            break
    if my_team is None:
        raise FetchError(
            "Could not find your team in ESPN league %s - check that the SWID "
            "cookie belongs to the account that owns a team there." % league_id
        )

    my_id = my_team.get("id")

    opponent_ids = []
    my_matchups = []
    for matchup in payload.get("schedule") or []:
        if matchup.get("matchupPeriodId") != week:
            continue
        home = (matchup.get("home") or {}).get("teamId")
        away = (matchup.get("away") or {}).get("teamId")
        if home == my_id and away is not None:
            opponent_ids.append(away)
            my_matchups.append((matchup, "home", "away"))
        elif away == my_id and home is not None:
            opponent_ids.append(home)
            my_matchups.append((matchup, "away", "home"))

    by_id = {team.get("id"): team for team in all_teams}

    players = {}
    points = {}

    def slots_for(team):
        slots = {}
        for player_id, slot, player, applied in _roster_entries(team):
            slots[player_id] = slot
            players[player_id] = player
            if applied is not None:
                points[player_id] = applied
        return slots

    settings = payload.get("settings") or {}

    def _side(entry, team):
        """One team's score, ESPN's own win probability, and its lineup."""
        # totalPointsLive updates during games; totalPoints is the settled value.
        live = entry.get("totalPointsLive")
        total = live if live else entry.get("totalPoints")
        lineup = []
        if team is not None:
            for player_id, slot, player, applied in _roster_entries(team):
                if slot in ("BN", "IR"):
                    continue
                lineup.append({
                    "player_id": player_id,
                    "slot": slot,
                    "points": applied,
                })
        return {
            "name": _team_name(team) if team is not None else "Opponent",
            "points": total,
            "projected": entry.get("totalProjectedPointsLive"),
            # ESPN publishes this per matchup side; Sleeper has no equivalent.
            "win_probability": entry.get("winProbability"),
            "starters": lineup,
        }

    matchup_detail = None
    if my_matchups:
        raw, mine_key, theirs_key = my_matchups[0]
        their_entry = raw.get(theirs_key) or {}
        their_team = by_id.get(their_entry.get("teamId"))
        matchup_detail = {
            "me": _side(raw.get(mine_key) or {}, my_team),
            "opponents": [_side(their_entry, their_team)],
        }

    return {
        "matchup": matchup_detail,
        "platform": "espn",
        "league_id": str(league_id),
        "league_name": settings.get("name") or "ESPN league %s" % league_id,
        "week": week,
        "my_slots": slots_for(my_team),
        "points": points,
        "opponents": [
            {"name": _team_name(by_id[oid]), "slots": slots_for(by_id[oid])}
            for oid in opponent_ids
            if oid in by_id
        ],
        "players": players,
    }
