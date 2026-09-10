#!/usr/bin/env python3
"""Check a Gmail app password before storing it, and store it once it works.

    python3 test_email.py

Nothing is echoed and nothing is written to shell history. Run this instead of
guessing through GitHub Actions, which takes a minute per attempt.
"""

import getpass
import subprocess
import sys

from fantasy import bundle, emailer, timezones


def main():
    print("-" * 62)
    print("GMAIL APP PASSWORD TEST")
    print("-" * 62)
    print("This needs the 16-character app password from")
    print("myaccount.google.com/apppasswords - NOT your normal Google password.")
    print("2-Step Verification must be switched on for that page to exist.\n")

    address = input("Gmail address [zcogginwps@gmail.com]: ").strip() \
        or "zcogginwps@gmail.com"
    password = getpass.getpass("App password (typing stays hidden): ")

    cleaned = "".join(password.split())
    if not cleaned:
        print("\nNothing entered.")
        return 1

    print("\n  address  : %s" % address)
    print("  length   : %d characters after removing spaces" % len(cleaned))
    if len(cleaned) != 16:
        print("  warning  : app passwords are exactly 16 letters. This is %d,"
              % len(cleaned))
        print("             which usually means it is the account password or")
        print("             the paste was incomplete.")

    bundle_data = bundle.load()
    if bundle_data:
        week = bundle_data["current"]["week"]
        day = bundle.find_day(bundle_data, week, bundle_data["current"]["date"])
    else:
        day, week = None, 1

    if day:
        html = emailer.build_html(day, week, bundle_data.get("change_lines"),
                                  app_url="https://zcogginwps.github.io/fantasy-game-day/")
        text = emailer.build_text(day, week, bundle_data.get("change_lines"))
        subject = "Test - %s" % day["date_label"]
    else:
        html = "<p>Fantasy Tracker test email.</p>"
        text = "Fantasy Tracker test email."
        subject = "Fantasy Tracker test"

    print("\n  Sending...")
    sent, error = emailer.send(subject, html, text, config={
        "user": address, "password": cleaned, "to": address, "sender": address})

    if not sent:
        print("\n  FAILED: %s" % error)
        print("\n  Try: generate a fresh app password at")
        print("  myaccount.google.com/apppasswords and run this again.")
        return 1

    print("  Sent. Check %s - it should arrive within a few seconds.\n" % address)

    if input("Store this as the GitHub secret now? (Y/n): ").strip().lower() \
            not in ("", "y", "yes"):
        print("Not stored.")
        return 0

    try:
        subprocess.run(["gh", "secret", "set", "SMTP_PASSWORD"],
                       input=cleaned.encode(), check=True)
        subprocess.run(["gh", "secret", "set", "SMTP_USER"],
                       input=address.encode(), check=True)
        print("\nStored. Game-day emails are on.")
    except (subprocess.SubprocessError, OSError) as exc:
        print("\nCould not store it automatically (%s)." % exc)
        print("Run this yourself:  gh secret set SMTP_PASSWORD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
