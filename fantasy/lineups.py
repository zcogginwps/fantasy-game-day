"""Snapshot lineups and diff them, so late roster moves get noticed.

Opponents can swap a starter minutes before kickoff. Each run records what every
lineup looked like; the next run compares against that and reports what moved.
"""

import json
import os

from . import config as config_module

SNAPSHOT_DIR = os.path.join(config_module.DATA_DIR, "lineups")

STARTING = "starting"
BENCH_SLOTS = ("BN", "IR", "TAXI")


def _is_starting(slot):
    return slot not in BENCH_SLOTS


def snapshot_path(date_iso):
    return os.path.join(SNAPSHOT_DIR, "%s.json" % date_iso)


def capture(leagues, name_lookup):
    """Reduce loaded leagues to {scope_key: {player_name: slot}}.

    Keyed by readable names rather than platform ids so a snapshot stays
    meaningful on its own.
    """
    snapshot = {}
    for league in leagues:
        league_name = league["league_name"]
        id_source = league.get("id_source") or league["platform"]

        def named(slots):
            out = {}
            for player_id, slot in (slots or {}).items():
                label = name_lookup(id_source, player_id, league)
                if label:
                    out[label] = slot
            return out

        snapshot["%s\x1fme" % league_name] = named(league.get("my_slots"))
        for opponent in league.get("opponents") or []:
            key = "%s\x1f%s" % (league_name, opponent["name"])
            snapshot[key] = named(opponent.get("slots"))
    return snapshot


def load(date_iso):
    path = snapshot_path(date_iso)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except (ValueError, IOError):
        return None


def save(date_iso, snapshot):
    if not os.path.isdir(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR)
    # No timestamp on purpose: the file is committed between runs, and a clock
    # value would make every run register as a change.
    payload = {"lineups": snapshot}
    path = snapshot_path(date_iso)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(payload, handle, indent=1)
    os.replace(tmp, path)


def diff(previous, current):
    """What changed between two snapshots.

    Only reports moves that cross the starting/bench line, or a player joining
    or leaving a roster. A shuffle from RB1 to RB2 is noise, not news.
    """
    if not previous:
        return []

    old_lineups = previous.get("lineups") or {}
    changes = []

    for scope, players in current.items():
        before = old_lineups.get(scope)
        if before is None:
            continue  # New league or new opponent: nothing to compare against.

        league, _, team = scope.partition("\x1f")
        side = "mine" if team == "me" else "opponent"

        for name, slot in players.items():
            was = before.get(name)
            if was is None:
                if _is_starting(slot):
                    changes.append({
                        "league": league, "side": side, "team": team,
                        "player": name, "kind": "added",
                        "from": None, "to": slot,
                    })
                continue
            if _is_starting(was) != _is_starting(slot):
                changes.append({
                    "league": league, "side": side, "team": team,
                    "player": name,
                    "kind": "started" if _is_starting(slot) else "benched",
                    "from": was, "to": slot,
                })

        for name, was in before.items():
            if name not in players and _is_starting(was):
                changes.append({
                    "league": league, "side": side, "team": team,
                    "player": name, "kind": "dropped",
                    "from": was, "to": None,
                })

    order = {"started": 0, "benched": 1, "added": 2, "dropped": 3}
    changes.sort(key=lambda c: (c["side"] != "opponent", order.get(c["kind"], 9),
                                c["league"], c["player"]))
    return changes


def describe(change):
    """One readable line for a notification or the terminal."""
    who = "You" if change["side"] == "mine" else change["team"]
    verbs = {
        "started": "moved %s into %s" % (change["player"], change["to"]),
        "benched": "benched %s" % change["player"],
        "added": "added %s at %s" % (change["player"], change["to"]),
        "dropped": "dropped %s" % change["player"],
    }
    return "%s: %s %s" % (change["league"], who, verbs.get(change["kind"], change["kind"]))
