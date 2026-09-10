"""The multi-week file the web app reads.

Weeks accumulate: collecting week 3 leaves weeks 1 and 2 in place, so the week
dropdown fills in as the season goes.
"""

import datetime
import json
import os

from . import config as config_module

BUNDLE_PATH = os.path.join(config_module.DATA_DIR, "report.json")
DEMO_PATH = os.path.join(config_module.DATA_DIR, "report-demo.json")


def path_for(demo=False):
    """Demo runs write their own file so real data is never clobbered."""
    return DEMO_PATH if demo else BUNDLE_PATH


def load(demo=False):
    path = path_for(demo)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except (ValueError, IOError):
        return None
    return data if isinstance(data, dict) and "weeks" in data else None


def merge(existing, week_reports, season, tz, current_week, current_date):
    """Fold freshly built weeks into whatever was already collected."""
    bundle = existing or {"weeks": {}}
    weeks = dict(bundle.get("weeks") or {})

    for report in week_reports:
        weeks[str(report["week"])] = report

    # Leagues can differ per week (a new league mid-season); show the union,
    # preferring the most recent week's naming.
    leagues = {}
    for key in sorted(weeks, key=lambda k: int(k)):
        for league in weeks[key].get("leagues") or []:
            leagues[league["name"]] = league

    now = datetime.datetime.now(tz)
    latest = weeks.get(str(current_week)) or {}

    return {
        "season": str(season),
        "timezone": str(tz),
        "generated_at": now.isoformat(),
        "generated_label": now.strftime("%-I:%M %p"),
        "current": {
            "week": int(current_week),
            "date": current_date.isoformat(),
        },
        "leagues": list(leagues.values()),
        "bench": latest.get("bench") or {},
        "weeks": weeks,
        "changes": latest.get("changes") or [],
        "change_lines": latest.get("change_lines") or [],
        "errors": latest.get("errors") or [],
    }


def save(bundle, demo=False):
    if not os.path.isdir(config_module.DATA_DIR):
        os.makedirs(config_module.DATA_DIR)
    path = path_for(demo)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(bundle, handle, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def find_day(bundle, week, date_iso):
    """One day out of the bundle, or None."""
    week_report = (bundle.get("weeks") or {}).get(str(week))
    if not week_report:
        return None
    for day in week_report.get("days") or []:
        if day["date"] == date_iso:
            return day
    return None


def parse_weeks(spec):
    """Turn "3", "1-4" or "all" into a list of week numbers."""
    text = (spec or "").strip().lower()
    if not text:
        return []
    if text == "all":
        return list(range(1, 19))
    weeks = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            start, _, end = part.partition("-")
            weeks.extend(range(int(start), int(end) + 1))
        elif part:
            weeks.append(int(part))
    return [w for w in weeks if 1 <= w <= 18]
