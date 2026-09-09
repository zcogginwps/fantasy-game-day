"""Build the daily cross-league report.

The hard part is identity: the same human is a Sleeper player id in one league
and an ESPN player id in another. Sleeper's player dictionary carries an
`espn_id` field, which gives us a reliable join key for everyone except team
defenses (whose ESPN ids are synthetic negatives) - those we join on team.
"""

import datetime
import re
import unicodedata

from . import espn as espn_client
from . import schedule as schedule_module
from . import sleeper as sleeper_client
from .webreq import FetchError

STARTING = "starting"
BENCH_SLOTS = ("BN", "IR", "TAXI")

# Sort order for the "what is this guy" column.
POSITION_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "FLEX": 4, "K": 5, "DEF": 6}

SEVERITY = {
    "Out": 4, "IR": 4, "Suspended": 4, "Doubtful": 3,
    "Questionable": 2, "Day-to-Day": 2, "Probable": 1, "": 0,
}


def _normalize_name(name):
    """Fold accents, drop punctuation and suffixes so names compare cleanly."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return re.sub(r"[^a-z]", "", text)


def canonical_key(record):
    """A stable id for one real player across both platforms."""
    if record.get("position") == "DEF" and record.get("team"):
        # ESPN gives defenses synthetic negative ids; Sleeper keys them by team
        # abbreviation. Team is the only thing both agree on.
        return "DEF|%s" % record["team"]
    if record.get("espn_id"):
        return "E|%s" % record["espn_id"]
    return "N|%s|%s" % (_normalize_name(record.get("name")), record.get("position") or "")


def _is_starting(slot):
    return slot not in BENCH_SLOTS


class PlayerRow(object):
    """One player, accumulated across every league they appear in."""

    def __init__(self, record):
        self.record = dict(record)
        self.for_me = []
        self.against_me = []

    def merge_record(self, other):
        """Fill gaps from a second source for the same player."""
        for field in ("team", "position", "injury_status", "injury_body_part", "espn_id"):
            if not self.record.get(field) and other.get(field):
                self.record[field] = other[field]
        # Prefer whichever source reports the more serious injury designation,
        # since a stale "healthy" reading is the dangerous direction to be wrong.
        mine = SEVERITY.get(self.record.get("injury_status"), 0)
        theirs = SEVERITY.get(other.get("injury_status"), 0)
        if theirs > mine:
            self.record["injury_status"] = other["injury_status"]
            if other.get("injury_body_part"):
                self.record["injury_body_part"] = other["injury_body_part"]

    @property
    def verdict(self):
        if self.for_me and self.against_me:
            return "both"
        if self.for_me:
            return "for"
        return "against"


def _resolve(record_key, records, row_index, record):
    row = row_index.get(record_key)
    if row is None:
        row = PlayerRow(record)
        row_index[record_key] = row
    else:
        row.merge_record(record)
    return row


def _collect_leagues(config, season, week, errors):
    """Load every configured league from both platforms."""
    leagues = []
    sleeper_players = {}

    # Sleeper's player dictionary is public and has fresher injury data than
    # ESPN's, so load it even when the user only plays on ESPN.
    try:
        sleeper_players = sleeper_client.get_players()
    except FetchError as exc:
        errors.append("Could not load the player database: %s" % exc)

    sleeper_config = config.get("sleeper") or {}
    username = (sleeper_config.get("username") or "").strip()
    if username:
        try:
            user = sleeper_client.get_user(username)
            for league in sleeper_client.get_leagues(user["user_id"], season):
                try:
                    loaded = sleeper_client.load_league(league, user["user_id"], week)
                except FetchError as exc:
                    errors.append("Sleeper league %s: %s" % (league.get("name"), exc))
                    continue
                if loaded:
                    leagues.append(loaded)
        except FetchError as exc:
            errors.append("Sleeper: %s" % exc)

    espn_config = config.get("espn") or {}
    if espn_config.get("espn_s2") and espn_config.get("swid"):
        league_ids = [str(x) for x in (espn_config.get("league_ids") or [])]
        if not league_ids and espn_config.get("auto_discover", True):
            league_ids = espn_client.discover_leagues(espn_config, season)
        for league_id in league_ids:
            try:
                leagues.append(
                    espn_client.load_league(league_id, season, week, espn_config)
                )
            except FetchError as exc:
                errors.append("ESPN league %s: %s" % (league_id, exc))

    return leagues, sleeper_players


def build(config, target_date, season, week, tz):
    """Assemble the full report for one calendar day."""
    errors = []
    games = schedule_module.games_on(target_date, tz)
    games_by_team = schedule_module.index_by_team(games)

    if config.get("demo"):
        from . import demo as demo_module
        leagues, sleeper_players = demo_module.build_leagues(target_date, tz)
    else:
        leagues, sleeper_players = _collect_leagues(config, season, week, errors)

    # Reverse index so an ESPN player id can find its richer Sleeper record.
    by_espn_id = {}
    for player_id, player in sleeper_players.items():
        if player.get("espn_id"):
            by_espn_id[str(player["espn_id"])] = player_id

    row_index = {}

    def record_for(id_source, player_id, league):
        """Look up the best available player record for a platform-local id."""
        if id_source == "sleeper":
            player = sleeper_players.get(player_id)
            if not player:
                return None
            return sleeper_client.player_record(player)

        # ESPN: prefer Sleeper's copy (fresher injuries, consistent naming).
        sleeper_id = by_espn_id.get(str(player_id))
        if sleeper_id and sleeper_id in sleeper_players:
            return sleeper_client.player_record(sleeper_players[sleeper_id])
        raw = (league.get("players") or {}).get(str(player_id))
        if raw:
            return espn_client.player_record(raw)
        return None

    for league in leagues:
        platform = league["platform"]
        # Which platform's player ids the roster uses. Normally the same as the
        # platform, but demo leagues are labelled ESPN while carrying Sleeper ids.
        id_source = league.get("id_source") or platform
        league_label = league["league_name"]

        for player_id, slot in (league.get("my_slots") or {}).items():
            record = record_for(id_source, player_id, league)
            if not record:
                continue
            row = _resolve(canonical_key(record), None, row_index, record)
            row.for_me.append({
                "league": league_label,
                "platform": platform,
                "slot": slot,
                "starting": _is_starting(slot),
            })

        for opponent in league.get("opponents") or []:
            for player_id, slot in (opponent.get("slots") or {}).items():
                record = record_for(id_source, player_id, league)
                if not record:
                    continue
                row = _resolve(canonical_key(record), None, row_index, record)
                row.against_me.append({
                    "league": league_label,
                    "platform": platform,
                    "slot": slot,
                    "opponent": opponent["name"],
                    "starting": _is_starting(slot),
                })

    include_bench = config.get("include_bench", True)

    players = []
    for row in row_index.values():
        team = row.record.get("team")
        game = games_by_team.get(team)
        if game is None:
            continue  # Not playing today - the whole point of the filter.

        if not include_bench:
            starting_anywhere = any(
                entry["starting"] for entry in row.for_me + row.against_me
            )
            if not starting_anywhere:
                continue

        game_dict = game.to_dict(tz)
        opponent_team = game.opponent_of(team)
        players.append({
            "name": row.record["name"],
            "position": row.record.get("position") or "",
            "team": team,
            "injury_status": row.record.get("injury_status") or "",
            "injury_body_part": row.record.get("injury_body_part") or "",
            "verdict": row.verdict,
            "kickoff_utc": game_dict["kickoff_utc"],
            "kickoff_label": game_dict["kickoff_label"],
            "game_label": game_dict["label"],
            "game_state": game_dict["state"],
            "matchup": "%s %s" % ("vs" if game.is_home(team) else "@", opponent_team),
            "for_me": sorted(row.for_me, key=lambda e: e["league"]),
            "against_me": sorted(row.against_me, key=lambda e: e["league"]),
            "starting_anywhere": any(
                e["starting"] for e in row.for_me + row.against_me
            ),
        })

    players.sort(key=lambda p: (
        p["kickoff_utc"],
        0 if p["starting_anywhere"] else 1,
        POSITION_ORDER.get(p["position"], 9),
        p["name"],
    ))

    return {
        "date": target_date.isoformat(),
        "date_label": target_date.strftime("%A, %B %-d"),
        "season": str(season),
        "week": week,
        "timezone": str(tz),
        "generated_at": datetime.datetime.now(tz).isoformat(),
        "generated_label": datetime.datetime.now(tz).strftime("%-I:%M %p"),
        "games": [g.to_dict(tz) for g in games],
        "leagues": [
            {
                "name": l["league_name"],
                "platform": l["platform"],
                "opponents": [o["name"] for o in l.get("opponents") or []],
            }
            for l in leagues
        ],
        "players": players,
        "counts": {
            "total": len(players),
            "for": len([p for p in players if p["verdict"] == "for"]),
            "against": len([p for p in players if p["verdict"] == "against"]),
            "both": len([p for p in players if p["verdict"] == "both"]),
        },
        "errors": errors,
    }
