# Phase 2 setup — notifications on your phone

What this adds:

- The app at a real `https://` address you can add to your iPhone Home Screen
- A push notification on game-day mornings and again ~2 hours before kickoff
- A push whenever an opponent changes their lineup
- The same rundown by email

Everything below is free.

## What runs where

GitHub stores the code and runs a scheduled job every 30 minutes. The job
collects your leagues, decides whether anything is worth sending, and publishes
the updated page to GitHub Pages.

The job runs often on purpose. GitHub's scheduler works in UTC and cannot follow
daylight saving, and kickoff times move around — so rather than guessing at a
clock, each run works out the local time and how far off the first kickoff is,
and stays quiet unless something is actually due.

## The pieces you provide

| Secret | What it is |
| --- | --- |
| `SLEEPER_USERNAME` | Your Sleeper username |
| `ESPN_S2`, `ESPN_SWID` | Your two ESPN cookies |
| `ESPN_LEAGUE_IDS` | Your ESPN league id |
| `VAPID_PRIVATE_KEY` | Signs push notifications (generated locally) |
| `PUSH_SUBSCRIPTION` | Identifies your phone (added after you install the app) |
| `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | For the email version |

Secrets are write-only once saved — GitHub never shows them again, and they are
not visible in logs.

## Gmail needs an app password

Gmail refuses ordinary passwords from scripts. You need a 16-character app
password, which requires 2-Step Verification on your Google account:

1. Go to **myaccount.google.com/security**
2. Turn on **2-Step Verification** if it is not already on
3. Go to **myaccount.google.com/apppasswords**
4. Type a name like `Fantasy Game Day` and press Create
5. Copy the 16-character code it shows — that is `SMTP_PASSWORD`

Your normal Google password is never used and never stored.

## Turning notifications on

Push has a chicken-and-egg step: your phone can only be registered after the app
exists at its real address.

1. Open the published address in **Safari** on your iPhone
2. Tap the **Share** button, then **Add to Home Screen**
3. Open the app from the new Home Screen icon — this matters, iOS only allows
   notifications from the installed app, not from a Safari tab
4. Scroll to the bottom, tap **Enable notifications**, allow when prompted
5. Tap **Copy to clipboard**
6. Send that text to yourself and store it as the `PUSH_SUBSCRIPTION` secret

That registration lasts indefinitely. If pushes ever stop, iOS has reset the
subscription — repeat steps 3 to 6.

## Checking it works

In your repository, open the **Actions** tab, choose **Game Day**, then **Run
workflow**. Set the dropdown to `morning` to send an alert immediately rather
than waiting for the schedule.

The run's log shows exactly what it decided and whether the push and email were
delivered.

## Changing the schedule

These are repository *variables* (Settings → Secrets and variables → Actions →
Variables), not secrets:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MORNING_HOUR` | `9` | Local hour for the morning alert |
| `KICKOFF_LEAD_MINUTES` | `120` | How long before the first kickoff to alert |
| `TIMEZONE` | `America/Chicago` | Your timezone |
| `APP_URL` | — | The published address, used in notification links |
| `INCLUDE_OPPONENT_BENCH` | `false` | Show opponents' bench players |

## What is public

The repository is public, which is what makes GitHub Pages and unlimited Actions
free. That means your league names, team names, opponents and rosters are
readable by anyone who finds the address.

Your credentials are **not** public — cookies, keys and passwords live in
secrets, and `config.json` is never committed.
