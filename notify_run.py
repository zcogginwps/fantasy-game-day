#!/usr/bin/env python3
"""The scheduled entrypoint that GitHub Actions runs.

Actions fires this on a fixed clock in UTC, but what should happen depends on
local time and on when the day's games start - so the workflow runs it often and
this decides whether anything is actually worth sending.

Three alerts:
  morning   once, from `morning_hour` local time, on days with games
  kickoff   once, a couple of hours before the day's first kickoff
  changes   whenever an opponent has moved someone since the last run
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

from fantasy import bundle as bundle_module
from fantasy import config as config_module
from fantasy import emailer
from fantasy import push
from fantasy import report as report_module
from fantasy import sleeper
from fantasy import timezones

STATE_DIR = os.path.join(config_module.DATA_DIR, "alerts")
APP_URL = os.environ.get("APP_URL", "").strip()


def state_path(date_iso):
    return os.path.join(STATE_DIR, "%s.json" % date_iso)


def load_state(date_iso):
    try:
        with open(state_path(date_iso), "r") as handle:
            return json.load(handle)
    except (IOError, ValueError):
        return {"sent": [], "changes": []}


def save_state(date_iso, state):
    if not os.path.isdir(STATE_DIR):
        os.makedirs(STATE_DIR)
    tmp = state_path(date_iso) + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    os.replace(tmp, state_path(date_iso))


def change_id(change):
    """A stable id so the same lineup move is not announced twice."""
    raw = "|".join(str(change.get(k)) for k in
                   ("league", "team", "player", "kind", "to"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def deliver(title, body, tag, want_email=False, html=None, text=None):
    """Send a push, and optionally an email. Never raises."""
    results = []

    try:
        delivered, errors = push.send(title, body, url=APP_URL or "./", tag=tag)
        results.append("push: %d sent" % delivered)
        results.extend("push: %s" % e for e in errors)
    except push.PushUnavailable as exc:
        results.append("push skipped: %s" % exc)

    if want_email and html:
        sent, error = emailer.send(title, html, text or body)
        results.append("email: sent" if sent else "email: %s" % error)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", choices=["morning", "kickoff"],
                        help="Send this alert regardless of the clock (for testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Decide and report, but send nothing")
    parser.add_argument("--morning-hour", type=int,
                        default=int(os.environ.get("MORNING_HOUR", 9)),
                        help="Local hour for the morning alert (default 9)")
    parser.add_argument("--kickoff-lead", type=int,
                        default=int(os.environ.get("KICKOFF_LEAD_MINUTES", 120)),
                        help="Minutes before first kickoff to alert (default 120)")
    args = parser.parse_args()

    try:
        conf = config_module.load()
    except config_module.ConfigError as exc:
        print("Config problem: %s" % exc, file=sys.stderr)
        return 2

    tz = timezones.zone(conf.get("timezone"))
    now = datetime.datetime.now(tz)
    today = now.date()

    season = sleeper.get_state().get("season") or str(today.year)
    week = int(sleeper.get_state().get("week") or 1)

    state = load_state(today.isoformat())

    # The current week is rebuilt every run for live scores. The rest of the
    # season is rebuilt once a day: matchups and rosters for future weeks do
    # change, but not minute to minute, and a full pass takes about a minute.
    if state.get("weeks_refreshed"):
        targets = [week]
    else:
        targets = sorted(set(range(1, 19)) | {week})
        print("Daily refresh of all %d weeks." % len(targets))

    reports = []
    for target in targets:
        reports.append(report_module.build_week(
            conf, season, target, tz,
            changes_for_date=today if target == week else None))
    merged = bundle_module.store(reports, season, tz, week, today)

    if not state.get("weeks_refreshed"):
        state["weeks_refreshed"] = True
        save_state(today.isoformat(), state)

    print("Collected %d week(s); week %s has %d days." % (
        len(targets), week,
        len((merged["weeks"].get(str(week)) or {}).get("days") or [])))

    day = bundle_module.find_day(merged, week, today.isoformat())
    if not day or not day["games"]:
        print("No NFL games today - nothing to send.")
        return 0

    counts = day["counts"]
    print("%s: %d players (%d for, %d against, %d conflicted)" % (
        day["date_label"], counts["total"], counts["for"],
        counts["against"], counts["both"]))

    want_email = (os.environ.get("SMTP_USER") or "") != ""
    sent = set(state.get("sent") or [])
    announced = set(state.get("changes") or [])
    actions = []

    first_kickoff = min(
        datetime.datetime.fromisoformat(g["kickoff_utc"]) for g in day["games"])
    minutes_to_kickoff = (
        first_kickoff - datetime.datetime.now(datetime.timezone.utc)
    ).total_seconds() / 60.0

    def summary_line():
        line = "%d for you, %d against you" % (counts["for"], counts["against"])
        if counts["both"]:
            line += ", %d conflicted" % counts["both"]
        hurt = [p["name"] for p in day["players"]
                if p["injury_status"] in ("Out", "Doubtful", "IR", "Suspended")]
        if hurt:
            line += " - OUT: %s" % ", ".join(hurt[:3])
        return line

    def html_body():
        return emailer.build_html(day, week, merged.get("change_lines"),
                                  app_url=APP_URL or None)

    def text_body():
        return emailer.build_text(day, week, merged.get("change_lines"))

    # --- morning ---------------------------------------------------------
    if args.force == "morning" or (
            "morning" not in sent and now.hour >= args.morning_hour):
        actions.append(("morning", day["date_label"], summary_line(), True))

    # --- a couple of hours before the first kickoff -----------------------
    if args.force == "kickoff" or (
            "kickoff" not in sent and 0 < minutes_to_kickoff <= args.kickoff_lead):
        actions.append(("kickoff", "Games start soon", summary_line(), True))

    # --- opponent lineup moves -------------------------------------------
    new_changes = [c for c in (merged.get("changes") or [])
                   if c["side"] == "opponent" and change_id(c) not in announced]
    if new_changes:
        lines = [merged["change_lines"][merged["changes"].index(c)]
                 for c in new_changes]
        actions.append(("changes", "Opponent lineup change",
                        " | ".join(lines[:3]), False))

    if not actions:
        print("Nothing to send right now (%s local, %d min to first kickoff)."
              % (now.strftime("%-I:%M %p"), minutes_to_kickoff))
        return 0

    for kind, title, body, email_it in actions:
        print("-> %s: %s | %s" % (kind, title, body))
        if args.dry_run:
            continue
        results = deliver(title, body, tag=kind,
                          want_email=email_it and want_email,
                          html=html_body(), text=text_body())
        for line in results:
            print("   %s" % line)

        if kind == "changes":
            announced.update(change_id(c) for c in new_changes)
        else:
            sent.add(kind)

    if not args.dry_run:
        save_state(today.isoformat(), {
            "sent": sorted(sent),
            "changes": sorted(announced),
            "weeks_refreshed": bool(state.get("weeks_refreshed")),
        })
    return 0


if __name__ == "__main__":
    sys.exit(main())
