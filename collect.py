#!/usr/bin/env python3
"""Build today's report and write it to data/report.json.

    python3 collect.py                 # today
    python3 collect.py --date 2026-09-13
    python3 collect.py --print         # also dump a text summary
"""

import argparse
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

from fantasy import config as config_module
from fantasy import report as report_module
from fantasy import sleeper


def resolve_week(season, target_date, override):
    """Which fantasy week `target_date` belongs to."""
    if override:
        return override
    state = sleeper.get_state()
    week = int(state.get("week") or 1)
    # Sleeper rolls its week over on Tuesday. When we are building a report for
    # a future date, step the week forward for each Tuesday in between.
    today = datetime.date.today()
    if target_date > today:
        cursor = today
        while cursor < target_date:
            cursor += datetime.timedelta(days=1)
            if cursor.weekday() == 1:  # Tuesday
                week += 1
    return max(1, min(week, 18))


def text_summary(data):
    lines = ["%s - Week %s" % (data["date_label"], data["week"]),
             "%d games, %d relevant players" % (len(data["games"]), data["counts"]["total"]),
             ""]
    symbol = {"for": "[FOR]", "against": "[AGAINST]", "both": "[BOTH]"}
    for player in data["players"]:
        parts = ["%-9s %-22s %-3s %-4s %-8s" % (
            symbol[player["verdict"]], player["name"], player["position"],
            player["team"], player["kickoff_label"])]
        if player["injury_status"]:
            parts.append("(%s)" % player["injury_status"])
        for entry in player["for_me"]:
            parts.append("+%s:%s" % (entry["league"], entry["slot"]))
        for entry in player["against_me"]:
            parts.append("-%s:%s" % (entry["league"], entry["slot"]))
        lines.append(" ".join(parts))
    for err in data["errors"]:
        lines.append("! %s" % err)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build the daily fantasy report.")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--week", type=int, help="Override the fantasy week")
    parser.add_argument("--season", help="Override the season year")
    parser.add_argument("--print", dest="show", action="store_true",
                        help="Print a text summary to the terminal")
    parser.add_argument("--demo", action="store_true",
                        help="Preview with invented leagues, no credentials needed")
    args = parser.parse_args()

    if args.demo:
        conf = dict(config_module.DEFAULTS)
        conf["demo"] = True
    else:
        try:
            conf = config_module.load()
        except config_module.ConfigError as exc:
            print("Config problem:\n%s" % exc, file=sys.stderr)
            return 2

    tz = ZoneInfo(conf.get("timezone") or "America/Chicago")

    if args.date:
        try:
            target = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print("--date must look like 2026-09-13", file=sys.stderr)
            return 2
    else:
        target = datetime.datetime.now(tz).date()

    season = args.season or sleeper.get_state().get("season") or str(target.year)
    week = resolve_week(season, target, args.week)

    data = report_module.build(conf, target, season, week, tz)

    if not os.path.isdir(config_module.DATA_DIR):
        os.makedirs(config_module.DATA_DIR)
    out = os.path.join(config_module.DATA_DIR, "report.json")
    tmp = out + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1)
    os.replace(tmp, out)

    # Keep a dated copy so the season builds up a history.
    archive = os.path.join(config_module.DATA_DIR, "report-%s.json" % data["date"])
    with open(archive, "w") as handle:
        json.dump(data, handle)

    print("%s: %d players across %d leagues (%d for, %d against, %d conflicted)" % (
        data["date_label"], data["counts"]["total"], len(data["leagues"]),
        data["counts"]["for"], data["counts"]["against"], data["counts"]["both"]))
    for err in data["errors"]:
        print("  ! %s" % err, file=sys.stderr)
    if args.show:
        print()
        print(text_summary(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
