#!/usr/bin/env python3
"""Build the week's report, and optionally keep watching for late lineup moves.

    python3 collect.py                 this week
    python3 collect.py --print         also print today's summary
    python3 collect.py --weeks 1-4     also collect other weeks
    python3 collect.py --watch         keep checking until the last kickoff
"""

import argparse
import datetime
import sys
import time

from fantasy import bundle as bundle_module
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
    # Sleeper rolls its week over on Tuesday, so stepping to a future date means
    # counting the Tuesdays in between.
    today = datetime.date.today()
    if target_date > today:
        cursor = today
        while cursor < target_date:
            cursor += datetime.timedelta(days=1)
            if cursor.weekday() == 1:  # Tuesday
                week += 1
    return max(1, min(week, 18))


def build_and_save(conf, season, weeks, tz, current_week, current_date):
    """Build the requested weeks and fold them into the saved bundle."""
    reports = []
    for week in weeks:
        reports.append(report_module.build_week(
            conf, season, week, tz,
            # Lineup diffing only makes sense for the day being watched.
            changes_for_date=current_date if week == current_week else None,
            current_week=current_week,
        ))
    demo = bool(conf.get("demo"))
    return bundle_module.store(
        reports, season, tz, current_week, current_date, demo)


def day_summary(day, week):
    if not day:
        return "No NFL games today."
    counts = day["counts"]
    return "%s: %d players (%d for, %d against, %d conflicted) - week %s" % (
        day["date_label"], counts["total"], counts["for"],
        counts["against"], counts["both"], week)


def text_summary(day, week, change_lines, errors):
    if not day:
        return "No NFL games today."
    lines = ["%s - Week %s" % (day["date_label"], week),
             "%d games, %d relevant players" % (
                 len(day["games"]), day["counts"]["total"]),
             ""]
    symbol = {"for": "[FOR]", "against": "[AGAINST]", "both": "[BOTH]"}
    for player in day["players"]:
        parts = ["%-9s %-22s %-3s %-4s %-8s" % (
            symbol[player["verdict"]], player["name"], player["position"],
            player["team"], player["kickoff_label"])]
        if player.get("score_label") and player.get("game_state") != "pre":
            parts.append("[%s]" % player["score_label"])
        if player["injury_status"]:
            parts.append("(%s)" % player["injury_status"])
        for entry in player["for_me"]:
            parts.append("+%s:%s" % (entry["league"], entry["slot"]))
        for entry in player["against_me"]:
            parts.append("-%s:%s" % (entry["league"], entry["slot"]))
        lines.append(" ".join(parts))
    if change_lines:
        lines.append("")
        lines.append("Lineup changes since the last check:")
        for line in change_lines:
            lines.append("  * %s" % line)
    for err in errors:
        lines.append("! %s" % err)
    return "\n".join(lines)


def watch(conf, season, tz, week, today, every_minutes, lead_minutes):
    """Poll until the day's last game has started."""
    notified_kickoffs = set()

    merged = build_and_save(conf, season, [week], tz, week, today)
    day = bundle_module.find_day(merged, week, today.isoformat())
    print(day_summary(day, week))

    if not day or not day["games"]:
        print("No NFL games today - nothing to watch.")
        return merged, day

    kickoffs = {g["label"]: datetime.datetime.fromisoformat(g["kickoff_utc"])
                for g in day["games"]}
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
                in_game = [p for p in day["players"] if p["game_label"] == label]
                notify.kickoff_summary(label, in_game)
                print("  [%s] kickoff alert: %s (%d players)" % (
                    datetime.datetime.now(tz).strftime("%-I:%M %p"),
                    label, len(in_game)))
                notified_kickoffs.add(label)

        if now > last_kickoff:
            print("\nLast game has kicked off. Done watching.")
            return merged, day

        time.sleep(every_minutes * 60)

        merged = build_and_save(conf, season, [week], tz, week, today)
        day = bundle_module.find_day(merged, week, today.isoformat()) or day
        stamp = datetime.datetime.now(tz).strftime("%-I:%M %p")
        change_lines = merged.get("change_lines") or []
        if change_lines:
            print("  [%s] %d lineup change(s):" % (stamp, len(change_lines)))
            for line in change_lines:
                print("      * %s" % line)
            notify.lineup_change_alert(merged.get("changes") or [])
        else:
            print("  [%s] no changes" % stamp)


def main():
    parser = argparse.ArgumentParser(description="Build the fantasy report.")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--week", type=int, help="Override the current week")
    parser.add_argument("--weeks", help='Also collect these weeks, e.g. "1-4" or "all"')
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
                        help="Send a Mac notification summarising the day")
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
            today = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print("--date must look like 2026-09-13", file=sys.stderr)
            return 2
    else:
        today = datetime.datetime.now(tz).date()

    season = args.season or sleeper.get_state().get("season") or str(today.year)
    week = resolve_week(today, args.week)

    if args.watch:
        merged, day = watch(conf, season, tz, week, today, args.every, args.lead)
    else:
        weeks = [week]
        for extra in bundle_module.parse_weeks(args.weeks):
            if extra not in weeks:
                weeks.append(extra)
        if len(weeks) > 1:
            print("Collecting weeks: %s" % ", ".join(str(w) for w in weeks))

        merged = build_and_save(conf, season, weeks, tz, week, today)
        day = bundle_module.find_day(merged, week, today.isoformat())

        print(day_summary(day, week))
        collected = sorted(int(k) for k in merged["weeks"])
        print("Weeks available in the app: %s" % ", ".join(str(w) for w in collected))

        if merged.get("change_lines"):
            print("Lineup changes since the last check:")
            for line in merged["change_lines"]:
                print("  * %s" % line)
        if args.notify and day and day["counts"]["total"]:
            notify.mac_notification(
                day["date_label"],
                "%d for you, %d against you, %d conflicted" % (
                    day["counts"]["for"], day["counts"]["against"],
                    day["counts"]["both"]),
                subtitle="Week %s" % week)

    for err in merged.get("errors") or []:
        print("  ! %s" % err, file=sys.stderr)
    if args.show:
        print()
        print(text_summary(day, week, merged.get("change_lines") or [],
                           merged.get("errors") or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
