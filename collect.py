#!/usr/bin/env python3
"""Build the day's report, and optionally keep watching for late lineup moves.

    python3 collect.py                 today's report
    python3 collect.py --print         also print a text summary
    python3 collect.py --watch         keep checking until the last kickoff
    python3 collect.py --date 2026-09-13
"""

import argparse
import datetime
import json
import os
import sys
import time

from fantasy import config as config_module
from fantasy import notify
from fantasy import report as report_module
from fantasy import sleeper
from fantasy import timezones


def resolve_week(target_date, override):
    """Which fantasy week `target_date` belongs to."""
    if override:
        return override
    state = sleeper.get_state()
    week = int(state.get("week") or 1)
    # Sleeper rolls its week over on Tuesday, so stepping forward to a future
    # date means counting the Tuesdays in between.
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
             "%d games, %d relevant players" % (
                 len(data["games"]), data["counts"]["total"]),
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
    if data["change_lines"]:
        lines.append("")
        lines.append("Lineup changes since the last check:")
        for line in data["change_lines"]:
            lines.append("  * %s" % line)
    for err in data["errors"]:
        lines.append("! %s" % err)
    return "\n".join(lines)


def write_report(data):
    if not os.path.isdir(config_module.DATA_DIR):
        os.makedirs(config_module.DATA_DIR)
    out = os.path.join(config_module.DATA_DIR, "report.json")
    tmp = out + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1)
    os.replace(tmp, out)

    archive = os.path.join(config_module.DATA_DIR, "report-%s.json" % data["date"])
    with open(archive, "w") as handle:
        json.dump(data, handle)
    return out


def summarise(data):
    return "%s: %d players across %d leagues (%d for, %d against, %d conflicted)" % (
        data["date_label"], data["counts"]["total"], len(data["leagues"]),
        data["counts"]["for"], data["counts"]["against"], data["counts"]["both"])


def run_once(conf, target, season, week, tz):
    data = report_module.build(conf, target, season, week, tz)
    write_report(data)
    return data


def watch(conf, target, season, week, tz, every_minutes, lead_minutes):
    """Poll until the day's last game has started.

    Two kinds of alert: an opponent changing their lineup, and a heads-up as
    each game is about to kick off.
    """
    notified_kickoffs = set()

    data = run_once(conf, target, season, week, tz)
    print(summarise(data))

    if not data["games"]:
        print("No NFL games today - nothing to watch.")
        return data

    kickoffs = {}
    for game in data["games"]:
        kickoffs[game["label"]] = datetime.datetime.fromisoformat(
            game["kickoff_utc"])
    last_kickoff = max(kickoffs.values())

    print("\nWatching %d game%s. Checking every %d minutes." % (
        len(kickoffs), "" if len(kickoffs) == 1 else "s", every_minutes))
    print("Alerts fire when an opponent changes their lineup, and %d minutes"
          % lead_minutes)
    print("before each kickoff. Press Control-C to stop.\n")

    while True:
        now = datetime.datetime.now(datetime.timezone.utc)

        for label, kickoff in sorted(kickoffs.items(), key=lambda kv: kv[1]):
            if label in notified_kickoffs:
                continue
            minutes_out = (kickoff - now).total_seconds() / 60.0
            if 0 < minutes_out <= lead_minutes:
                in_game = [p for p in data["players"] if p["game_label"] == label]
                notify.kickoff_summary(label, in_game)
                print("  [%s] kickoff alert: %s (%d players)" % (
                    datetime.datetime.now(tz).strftime("%-I:%M %p"),
                    label, len(in_game)))
                notified_kickoffs.add(label)

        if now > last_kickoff:
            print("\nLast game has kicked off. Done watching.")
            return data

        time.sleep(every_minutes * 60)

        data = run_once(conf, target, season, week, tz)
        stamp = datetime.datetime.now(tz).strftime("%-I:%M %p")
        if data["changes"]:
            print("  [%s] %d lineup change(s):" % (stamp, len(data["changes"])))
            for line in data["change_lines"]:
                print("      * %s" % line)
            notify.lineup_change_alert(data["changes"])
        else:
            print("  [%s] no changes" % stamp)


def main():
    parser = argparse.ArgumentParser(description="Build the daily fantasy report.")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--week", type=int, help="Override the fantasy week")
    parser.add_argument("--season", help="Override the season year")
    parser.add_argument("--print", dest="show", action="store_true",
                        help="Print a text summary to the terminal")
    parser.add_argument("--demo", action="store_true",
                        help="Preview with invented leagues, no credentials needed")
    parser.add_argument("--watch", action="store_true",
                        help="Keep checking for lineup changes until the last kickoff")
    parser.add_argument("--every", type=int, default=10,
                        help="Minutes between checks when watching (default 10)")
    parser.add_argument("--lead", type=int, default=15,
                        help="Minutes before kickoff to alert (default 15)")
    parser.add_argument("--notify", action="store_true",
                        help="Send a Mac notification summarising the report")
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

    try:
        tz = timezones.zone(conf.get("timezone"))
    except ValueError as exc:
        print("Config problem:\n%s\n\nFix the \"timezone\" line in config.json, "
              "or rerun: python3 setup_wizard.py" % exc, file=sys.stderr)
        return 2

    if args.date:
        try:
            target = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print("--date must look like 2026-09-13", file=sys.stderr)
            return 2
    else:
        target = datetime.datetime.now(tz).date()

    season = args.season or sleeper.get_state().get("season") or str(target.year)
    week = resolve_week(target, args.week)

    if args.watch:
        data = watch(conf, target, season, week, tz, args.every, args.lead)
    else:
        data = run_once(conf, target, season, week, tz)
        print(summarise(data))
        if data["change_lines"]:
            print("Lineup changes since the last check:")
            for line in data["change_lines"]:
                print("  * %s" % line)
        if args.notify and data["counts"]["total"]:
            notify.mac_notification(
                data["date_label"],
                "%d for you, %d against you, %d conflicted" % (
                    data["counts"]["for"], data["counts"]["against"],
                    data["counts"]["both"]),
                subtitle="Week %s" % data["week"])

    for err in data["errors"]:
        print("  ! %s" % err, file=sys.stderr)
    if args.show:
        print()
        print(text_summary(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
