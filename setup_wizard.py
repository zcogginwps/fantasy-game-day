#!/usr/bin/env python3
"""Interactive first-time setup. Writes config.json.

    python3 setup_wizard.py
"""

import os
import sys

from fantasy import config as config_module
from fantasy import espn as espn_client
from fantasy import sleeper as sleeper_client
from fantasy.webreq import FetchError

RULE = "-" * 62


def detect_timezone():
    """Read the timezone macOS has already configured."""
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "America/Chicago"


def ask(prompt, default=""):
    suffix = " [%s]" % default if default else ""
    try:
        answer = input("%s%s: " % (prompt, suffix)).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        sys.exit(1)
    return answer or default


def yes_no(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    answer = ask("%s (%s)" % (prompt, hint)).lower()
    if not answer:
        return default
    return answer.startswith("y")


def setup_sleeper(config):
    print("\n" + RULE)
    print("SLEEPER")
    print(RULE)
    print("Sleeper needs only your username - no password, no cookies.")
    print("It is the name on your Sleeper profile, not your email.\n")

    if not yes_no("Do you use Sleeper?"):
        config["sleeper"]["username"] = ""
        return

    while True:
        username = ask("Sleeper username")
        if not username:
            config["sleeper"]["username"] = ""
            return
        try:
            user = sleeper_client.get_user(username)
        except FetchError:
            print("  x No Sleeper user called %r. Check the spelling.\n" % username)
            continue

        season = sleeper_client.get_state().get("season")
        leagues = sleeper_client.get_leagues(user["user_id"], season)
        print("  ok Found %s - %d league(s) for %s:" % (
            user.get("display_name") or username, len(leagues), season))
        for league in leagues:
            print("       - %s" % league.get("name"))
        config["sleeper"]["username"] = username
        return


def setup_espn(config):
    print("\n" + RULE)
    print("ESPN")
    print(RULE)
    print("ESPN has no public API, so we reuse the login your browser already")
    print("has. You need two cookie values: espn_s2 and SWID.\n")
    print("  1. Open Chrome and sign in at fantasy.espn.com")
    print("  2. Press Option-Command-I to open developer tools")
    print("  3. Click the 'Application' tab at the top")
    print("  4. In the left sidebar: Storage > Cookies > https://fantasy.espn.com")
    print("  5. Find the rows named 'espn_s2' and 'SWID', copy each Value\n")
    print("The espn_s2 value is very long. SWID looks like {AAAA-BBBB-...}.\n")

    if not yes_no("Do you use ESPN fantasy?"):
        config["espn"]["espn_s2"] = ""
        config["espn"]["swid"] = ""
        return

    espn_s2 = ask("espn_s2")
    swid = ask("SWID")
    if not espn_s2 or not swid:
        print("  ! Skipping ESPN - both values are required.")
        config["espn"]["espn_s2"] = ""
        config["espn"]["swid"] = ""
        return

    config["espn"]["espn_s2"] = espn_s2
    config["espn"]["swid"] = swid

    season = sleeper_client.get_state().get("season")
    print("\n  Looking up your ESPN leagues...")
    league_ids = espn_client.discover_leagues(config["espn"], season)

    if league_ids:
        working = []
        for league_id in league_ids:
            try:
                loaded = espn_client.load_league(league_id, season, 1, config["espn"])
                print("    ok %s (id %s)" % (loaded["league_name"], league_id))
                working.append(league_id)
            except FetchError as exc:
                print("    x  league %s: %s" % (league_id, exc))
        config["espn"]["league_ids"] = working
    else:
        print("    ! Could not auto-detect leagues.")
        print("      Open a league on fantasy.espn.com and copy the number after")
        print("      'leagueId=' in the address bar. Separate several with commas.")
        raw = ask("ESPN league IDs (comma separated, blank to skip)")
        config["espn"]["league_ids"] = [
            part.strip() for part in raw.split(",") if part.strip()
        ]


def main():
    print(RULE)
    print("FANTASY GAME DAY - SETUP")
    print(RULE)

    config = {
        "timezone": "",
        "include_bench": True,
        "sleeper": {"username": ""},
        "espn": {"espn_s2": "", "swid": "", "league_ids": [], "auto_discover": True},
    }

    detected = detect_timezone()
    config["timezone"] = ask("\nYour timezone", detected)

    setup_sleeper(config)
    setup_espn(config)

    config["include_bench"] = yes_no(
        "\nInclude bench players in the report?", True)

    if not config["sleeper"]["username"] and not config["espn"]["espn_s2"]:
        print("\nNothing configured - no Sleeper username and no ESPN cookies.")
        return 1

    config_module.save(config)
    print("\n" + RULE)
    print("Saved to config.json (readable only by you).")
    print(RULE)
    print("\nNext:")
    print("  python3 collect.py --print     build today's report")
    print("  python3 serve.py               open it on your phone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
