"""Build the daily cross-league report.

The hard part is identity: the same human is a Sleeper player id in one league
and an ESPN player id in another. Sleeper's player dictionary usually carries an
`espn_id`, which gives a reliable join key - but not always (Romeo Doubs, for
one, has none). So each player is filed under every id we can derive for them,
and any row found under any of those keys is the same person.
"""

import datetime
import re
import unicodedata

from . import espn as espn_client
from . import lineups as lineups_module
from . import schedule as schedule_module
from . import sleeper as sleeper_client
from .webreq import FetchError

BENCH_SLOTS = ("BN", "IR", "TAXI")

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


def _name_key(record):
    return "N|%s|%s" % (
        _normalize_name(record.get("name")), record.get("position") or "")


def candidate_keys(record):
    """Every id this player might already be filed under.

    Returning several keys is what lets a Sleeper record with no espn_id still
    merge with the ESPN copy of the same player.
    """
    if record.get("position") == "DEF" and record.get("team"):
        # ESPN gives defenses synthetic negative ids; team is the only thing
        # both platforms agree on.
        return ["DEF|%s" % record["team"]]

    keys = []
    if record.get("espn_id"):
        keys.append("E|%s" % record["espn_id"])
    keys.append(_name_key(record))
    return keys


def _is_starting(slot):
    return slot not in BENCH_SLOTS


class PlayerRow(object):
    """One player, accumulated across every league they appear in."""

    def __init__(self, record):
        self.record = dict(record)
        self.for_me = []
        self.against_me = []

    def merge_record(self, other):
        for field in ("team", "position", "espn_id"):
            if not self.record.get(field) and other.get(field):
                self.record[field] = other[field]

        mine_is_sleeper = self.record.get("source") == "sleeper"
        theirs_is_sleeper = other.get("source") == "sleeper"

        if theirs_is_sleeper and not mine_is_sleeper:
            # Sleeper is the authority on injury status, always.
            self.record["injury_status"] = other.get("injury_status") or ""
            self.record["injury_body_part"] = other.get("injury_body_part") or ""
            self.record["source"] = "sleeper"
        elif not mine_is_sleeper and not theirs_is_sleeper:
            # Neither side is authoritative, so err toward the worse news.
            if SEVERITY.get(other.get("injury_status"), 0) > SEVERITY.get(
                    self.record.get("injury_status"), 0):
                self.record["injury_status"] = other["injury_status"]

    @property
    def verdict(self):
        if self.for_me and self.against_me:
            return "both"
        if self.for_me:
            return "for"
        return "against"


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
        if espn_config.get("auto_discover", True):
            for found in espn_client.discover_leagues(espn_config, season):
                if found not in league_ids:
                    league_ids.append(found)
        for league_id in league_ids:
            try:
                leagues.append(
                    espn_client.load_league(league_id, season, week, espn_config)
                )
            except FetchError as exc:
                errors.append("ESPN league %s: %s" % (league_id, exc))

    return leagues, sleeper_players


def _bench_settings(config):
    """Bench visibility, with the older single include_bench flag honoured."""
    legacy = config.get("include_bench")
    mine = config.get("include_my_bench")
    theirs = config.get("include_opponent_bench")
    if mine is None:
        mine = True if legacy is None else legacy
    if theirs is None:
        theirs = False if legacy is None else legacy
    return bool(mine), bool(theirs)


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

    # Two ways into Sleeper's data, because espn_id is not always present.
    by_espn_id = {}
    by_name = {}
    for player_id, player in sleeper_players.items():
        if player.get("espn_id"):
            by_espn_id[str(player["espn_id"])] = player_id
        record = sleeper_client.player_record(player)
        by_name.setdefault(_name_key(record), player_id)

    def record_for(id_source, player_id, league):
        """The best available player record for a platform-local id."""
        if id_source == "sleeper":
            player = sleeper_players.get(player_id)
            return sleeper_client.player_record(player) if player else None

        raw = (league.get("players") or {}).get(str(player_id))

        # Prefer Sleeper's copy: the user wants injury status to come from
        # Sleeper even for players they roster on ESPN.
        sleeper_id = by_espn_id.get(str(player_id))
        if not sleeper_id and raw:
            sleeper_id = by_name.get(_name_key(espn_client.player_record(raw)))
        if sleeper_id and sleeper_id in sleeper_players:
            return sleeper_client.player_record(sleeper_players[sleeper_id])

        return espn_client.player_record(raw) if raw else None

    include_my_bench, include_opponent_bench = _bench_settings(config)

    row_index = {}
    # Every rostered player whose NFL team plays today, regardless of whether
    # the bench settings will show them. Lineup changes are judged against this
    # so that an opponent benching a starter still counts as news.
    todays_names = set()

    def resolve(record):
        keys = candidate_keys(record)
        row = None
        for key in keys:
            if key in row_index:
                row = row_index[key]
                break
        if row is None:
            row = PlayerRow(record)
        else:
            row.merge_record(record)
        for key in keys:
            row_index[key] = row  # File under every alias so later ids match.
        return row

    for league in leagues:
        id_source = league.get("id_source") or league["platform"]
        league_label = league["league_name"]

        for player_id, slot in (league.get("my_slots") or {}).items():
            record = record_for(id_source, player_id, league)
            if not record:
                continue
            if games_by_team.get(record.get("team")):
                todays_names.add(record["name"])
            if not include_my_bench and not _is_starting(slot):
                continue
            resolve(record).for_me.append({
                "league": league_label, "platform": league["platform"],
                "slot": slot, "starting": _is_starting(slot),
            })

        for opponent in league.get("opponents") or []:
            for player_id, slot in (opponent.get("slots") or {}).items():
                record = record_for(id_source, player_id, league)
                if not record:
                    continue
                if games_by_team.get(record.get("team")):
                    todays_names.add(record["name"])
                if not include_opponent_bench and not _is_starting(slot):
                    continue
                resolve(record).against_me.append({
                    "league": league_label, "platform": league["platform"],
                    "slot": slot, "opponent": opponent["name"],
                    "starting": _is_starting(slot),
                })

    # Late lineup moves: compare against what we saw on the previous run.
    def name_lookup(id_source, player_id, league):
        record = record_for(id_source, player_id, league)
        return record["name"] if record else None

    snapshot = lineups_module.capture(leagues, name_lookup)
    previous = lineups_module.load(target_date.isoformat())
    changes = lineups_module.diff(previous, snapshot)
    lineups_module.save(target_date.isoformat(), snapshot)

    # One row can be filed under several keys, so collapse to unique rows.
    unique_rows = list({id(row): row for row in row_index.values()}.values())

    players = []
    for row in unique_rows:
        if not row.for_me and not row.against_me:
            continue
        team = row.record.get("team")
        game = games_by_team.get(team)
        if game is None:
            continue  # Not playing today - the whole point of the filter.

        game_dict = game.to_dict(tz)
        opponent_team = game.opponent_of(team)
        players.append({
            "name": row.record["name"],
            "position": row.record.get("position") or "",
            "team": team,
            "injury_status": row.record.get("injury_status") or "",
            "injury_body_part": row.record.get("injury_body_part") or "",
            "injury_source": row.record.get("source") or "",
            "verdict": row.verdict,
            "kickoff_utc": game_dict["kickoff_utc"],
            "kickoff_label": game_dict["kickoff_label"],
            "game_label": game_dict["label"],
            "game_state": game_dict["state"],
            "matchup": "%s %s" % ("vs" if game.is_home(team) else "@", opponent_team),
            "for_me": sorted(row.for_me, key=lambda e: e["league"]),
            "against_me": sorted(row.against_me, key=lambda e: e["league"]),
            "starting_anywhere": any(
                e["starting"] for e in row.for_me + row.against_me),
        })

    players.sort(key=lambda p: (
        p["kickoff_utc"],
        0 if p["starting_anywhere"] else 1,
        POSITION_ORDER.get(p["position"], 9),
        p["name"],
    ))

    # A change only matters today if that player is actually in a game today.
    relevant_changes = [c for c in changes if c["player"] in todays_names]

    return {
        "date": target_date.isoformat(),
        "date_label": target_date.strftime("%A, %B %-d"),
        "season": str(season),
        "week": week,
        "timezone": str(tz),
        "generated_at": datetime.datetime.now(tz).isoformat(),
        "generated_label": datetime.datetime.now(tz).strftime("%-I:%M %p"),
        "bench": {"mine": include_my_bench, "opponent": include_opponent_bench},
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
        "changes": relevant_changes,
        "change_lines": [lineups_module.describe(c) for c in relevant_changes],
        "counts": {
            "total": len(players),
            "for": len([p for p in players if p["verdict"] == "for"]),
            "against": len([p for p in players if p["verdict"] == "against"]),
            "both": len([p for p in players if p["verdict"] == "both"]),
            "changes": len(relevant_changes),
        },
        "errors": errors,
    }
