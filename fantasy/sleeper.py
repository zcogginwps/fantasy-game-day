"""Sleeper client.

Sleeper's read API is fully public - no key, no cookies - so all we need from
the user is their username.
"""

from . import teams
from .webreq import FetchError, get_json, get_json_cached

BASE = "https://api.sleeper.app/v1"

# The player dictionary is ~14MB and changes at most once a day.
PLAYER_CACHE_SECONDS = 12 * 60 * 60


def get_state():
    """Current NFL season and week, as Sleeper sees it."""
    return get_json("%s/state/nfl" % BASE)


def get_user(username):
    user = get_json("%s/user/%s" % (BASE, username))
    if not user or not user.get("user_id"):
        raise FetchError("Sleeper has no user named %r" % username)
    return user


def get_players():
    """The full NFL player dictionary, keyed by Sleeper player id."""
    return get_json_cached(
        "%s/players/nfl" % BASE,
        PLAYER_CACHE_SECONDS,
        "sleeper_players",
    )


def get_leagues(user_id, season):
    return get_json("%s/user/%s/leagues/nfl/%s" % (BASE, user_id, season)) or []


def _slot_labels(roster_positions):
    """Turn a league's slot template into display labels for the starters array.

    `roster_positions` looks like ["QB","RB","RB","WR","WR","TE","FLEX","K","DEF","BN","BN"].
    The starters array lines up positionally with that list once bench and
    reserve slots are removed, and repeated positions get numbered so the user
    sees "RB2" rather than a second, ambiguous "RB".
    """
    active = [p for p in roster_positions if p not in ("BN", "IR", "TAXI")]

    counts = {}
    for slot in active:
        counts[slot] = counts.get(slot, 0) + 1

    seen = {}
    labels = []
    for slot in active:
        if counts[slot] > 1:
            seen[slot] = seen.get(slot, 0) + 1
            labels.append("%s%d" % (slot, seen[slot]))
        else:
            labels.append(slot)
    return labels


def build_roster_slots(league, roster, starters):
    """Map every player id on a roster to the slot they occupy.

    Returns {player_id: label}, where label is a starting slot ("RB2", "FLEX"),
    "BN", or "IR".
    """
    labels = _slot_labels(league.get("roster_positions") or [])

    slots = {}
    for index, player_id in enumerate(starters or []):
        # Sleeper pads empty starting slots with "0".
        if not player_id or player_id == "0":
            continue
        slots[player_id] = labels[index] if index < len(labels) else "STARTER"

    for player_id in roster.get("reserve") or []:
        slots.setdefault(player_id, "IR")
    for player_id in roster.get("taxi") or []:
        slots.setdefault(player_id, "TAXI")
    for player_id in roster.get("players") or []:
        slots.setdefault(player_id, "BN")

    return slots


def owns_roster(roster, user_id):
    """Whether the given user owns this roster, including as a co-owner."""
    if roster.get("owner_id") == user_id:
        return True
    return user_id in (roster.get("co_owners") or [])


def load_league(league, user_id, week):
    """Pull everything needed from one Sleeper league.

    Returns a dict with my roster slots and each opponent roster's slots, or
    None when the user has no team in the league.
    """
    league_id = league["league_id"]
    rosters = get_json("%s/league/%s/rosters" % (BASE, league_id)) or []
    users = get_json("%s/league/%s/users" % (BASE, league_id)) or []

    display_names = {}
    for user in users:
        metadata = user.get("metadata") or {}
        display_names[user["user_id"]] = (
            metadata.get("team_name") or user.get("display_name") or "Unknown"
        )

    my_roster = None
    for roster in rosters:
        if owns_roster(roster, user_id):
            my_roster = roster
            break
    if my_roster is None:
        return None

    # Matchups carry the week's actual starting lineup; the roster object only
    # holds the season-long default. Fall back to the roster if the week has not
    # been posted yet (e.g. before the season opens).
    try:
        matchups = get_json("%s/league/%s/matchups/%s" % (BASE, league_id, week)) or []
    except FetchError:
        matchups = []

    by_roster_id = {m.get("roster_id"): m for m in matchups}

    def starters_for(roster):
        matchup = by_roster_id.get(roster.get("roster_id"))
        if matchup and matchup.get("starters"):
            return matchup["starters"]
        return roster.get("starters") or []

    my_matchup = by_roster_id.get(my_roster.get("roster_id")) or {}
    my_matchup_id = my_matchup.get("matchup_id")

    opponents = []
    if my_matchup_id is not None:
        for roster in rosters:
            if roster.get("roster_id") == my_roster.get("roster_id"):
                continue
            other = by_roster_id.get(roster.get("roster_id")) or {}
            if other.get("matchup_id") == my_matchup_id:
                opponents.append(roster)

    def owner_label(roster):
        return display_names.get(roster.get("owner_id"), "Opponent")

    return {
        "platform": "sleeper",
        "league_id": str(league_id),
        "league_name": league.get("name") or "Sleeper league",
        "week": week,
        "my_slots": build_roster_slots(league, my_roster, starters_for(my_roster)),
        "opponents": [
            {
                "name": owner_label(roster),
                "slots": build_roster_slots(league, roster, starters_for(roster)),
            }
            for roster in opponents
        ],
    }


def player_record(player):
    """Normalise a Sleeper player entry into the shared shape."""
    name = player.get("full_name") or " ".join(
        filter(None, [player.get("first_name"), player.get("last_name")])
    )
    return {
        "name": name or "Unknown player",
        "position": player.get("position") or "",
        "team": teams.normalize(player.get("team")),
        "injury_status": player.get("injury_status") or "",
        "injury_body_part": player.get("injury_body_part") or "",
        "espn_id": str(player["espn_id"]) if player.get("espn_id") else None,
    }
