# Fantasy Game Day

Every NFL game day, one screen showing which players are on the field for you
and which are on the field against you — across all of your Sleeper and ESPN
leagues at once.

Each player is colour-coded:

- **Green** — only playing *for* you
- **Red** — only playing *against* you
- **Yellow** — playing for you in some leagues and against you in others

Alongside each player: injury status, kickoff time, the roster slot they occupy,
a green column listing every league where they play for you, and a red column
listing every league where they play against you.

## Requirements

Nothing to install. It runs on the Python that ships with macOS and uses only
the standard library.

## Setup

1. Open Terminal and go to the project:

       cd ~/Documents/Claude/fantasy-monitor

2. Run the setup wizard and answer its questions:

       python3 setup_wizard.py

   It asks for your Sleeper username (that alone is enough for Sleeper) and,
   for ESPN, two cookie values from a browser where you are logged in. The
   wizard prints step-by-step instructions for finding them.

3. Build today's report:

       python3 collect.py --print

4. Open it on your phone:

       python3 serve.py

   That prints two addresses. Type the "On your phone" one into Safari while
   your phone is on the same wifi. To keep it handy, tap the Share button and
   choose "Add to Home Screen".

Press Control-C in Terminal to stop the server.

## Trying it without credentials

To see the interface with invented leagues built from real NFL players:

    python3 collect.py --demo --date 2026-09-13
    python3 serve.py

## Commands

| Command | What it does |
| --- | --- |
| `python3 setup_wizard.py` | Create or replace `config.json` |
| `python3 collect.py` | Build today's report |
| `python3 collect.py --date 2026-09-13` | Build a specific day |
| `python3 collect.py --print` | Also print a text summary |
| `python3 collect.py --demo` | Fake leagues, no credentials needed |
| `python3 serve.py` | Serve the app on your local network |
| `python3 build_static.py` | Bundle the report into one HTML file |

## How it works

- **Sleeper** has a fully public read API — a username is all it needs.
- **ESPN** has no public API, so this calls the same endpoint their web app
  uses, authenticated with your `espn_s2` and `SWID` cookies. Those cookies
  eventually expire; rerun the wizard when ESPN leagues start failing.
- **The schedule** and kickoff times come from ESPN's public scoreboard.
- **Matching players across platforms** is the tricky part. Sleeper's player
  records include an `espn_id`, which gives a reliable join key. Team defenses
  are the exception — ESPN gives them synthetic negative ids — so those are
  matched on team instead.
- **Injury data** prefers whichever source reports the more serious
  designation, since a stale "healthy" reading is the dangerous way to be wrong.

`config.json` holds your ESPN session cookies. It is written readable only by
you and is excluded from version control.

## Status

Phase 1 (this) runs on your Mac and shows the report in a browser.

Phase 2 adds the automatic game-day notifications — a push notification in the
morning and a second one before the first kickoff, plus optional email. That
requires internet hosting, because iOS only delivers web push from an HTTPS
site.
