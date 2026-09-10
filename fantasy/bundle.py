"""The multi-week file the web app reads.

Each week is stored as its own file and the browser-facing bundle is assembled
from whatever weeks exist. Keeping them separate matters in CI: the weeks are
committed back to the repository between scheduled runs, and a per-week file
only changes when that week's data actually changes, rather than every run.
"""

import datetime
import json
import os

from . import config as config_module

BUNDLE_PATH = os.path.join(config_module.DATA_DIR, "report.json")
DEMO_PATH = os.path.join(config_module.DATA_DIR, "report-demo.json")
WEEKS_DIR = os.path.join(config_module.DATA_DIR, "weeks")
DEMO_WEEKS_DIR = os.path.join(config_module.DATA_DIR, "weeks-demo")


def path_for(demo=False):
    """Demo runs write their own files so real data is never clobbered."""
    return DEMO_PATH if demo else BUNDLE_PATH


def weeks_dir(demo=False):
    return DEMO_WEEKS_DIR if demo else WEEKS_DIR


def save_week(report, demo=False):
    """Store one week on its own.

    Sorted keys and no timestamp, so an unchanged week produces a
    byte-identical file and no spurious commit.
    """
    directory = weeks_dir(demo)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = os.path.join(directory, "%d.json" % int(report["week"]))
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(report, handle, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)
    return path


def load_weeks(demo=False):
    directory = weeks_dir(demo)
    weeks = {}
    if not os.path.isdir(directory):
        return weeks
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), "r") as handle:
                report = json.load(handle)
            weeks[str(int(report["week"]))] = report
        except (ValueError, IOError, KeyError, TypeError):
            continue  # A half-written or stale file should not break the app.
    return weeks


def assemble(weeks, season, tz, current_week, current_date):
    """Build the single file the web app fetches."""
    # Leagues can differ per week (a league joined mid-season); show the union,
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
        "current": {"week": int(current_week), "date": current_date.isoformat()},
        "leagues": list(leagues.values()),
        "bench": latest.get("bench") or {},
        "weeks": weeks,
        "changes": latest.get("changes") or [],
        "change_lines": latest.get("change_lines") or [],
        "errors": latest.get("errors") or [],
    }


def store(reports, season, tz, current_week, current_date, demo=False):
    """Save the given weeks, then rebuild and save the bundle."""
    for report in reports:
        save_week(report, demo)
    weeks = load_weeks(demo)
    bundle = assemble(weeks, season, tz, current_week, current_date)
    save(bundle, demo)
    return bundle


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
