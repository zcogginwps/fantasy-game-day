"""The day's NFL games, from ESPN's public scoreboard endpoint (no auth)."""

import datetime

from . import teams
from .webreq import get_json

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


class Game(object):
    """One NFL game, with kickoff already converted to the user's timezone."""

    def __init__(self, event_id, kickoff_utc, home, away, state, status_detail):
        self.event_id = event_id
        self.kickoff_utc = kickoff_utc
        self.home = home
        self.away = away
        self.state = state
        self.status_detail = status_detail

    def opponent_of(self, team):
        """Who the given team is facing in this game."""
        return self.away if team == self.home else self.home

    def is_home(self, team):
        return team == self.home

    def to_dict(self, tz):
        local = self.kickoff_utc.astimezone(tz)
        return {
            "event_id": self.event_id,
            "kickoff_utc": self.kickoff_utc.isoformat(),
            "kickoff_local": local.isoformat(),
            # e.g. "1:00 PM" - strip the zero-padding macOS strftime leaves behind.
            "kickoff_label": local.strftime("%-I:%M %p"),
            "home": self.home,
            "away": self.away,
            "state": self.state,
            "status_detail": self.status_detail,
            "label": "%s @ %s" % (self.away, self.home),
        }


def _parse_event(event):
    competition = event["competitions"][0]
    home = away = None
    for competitor in competition["competitors"]:
        abbr = teams.normalize(competitor["team"].get("abbreviation"))
        if competitor.get("homeAway") == "home":
            home = abbr
        else:
            away = abbr

    kickoff = datetime.datetime.strptime(
        event["date"], "%Y-%m-%dT%H:%MZ"
    ).replace(tzinfo=datetime.timezone.utc)

    status = event.get("status", {}).get("type", {})
    return Game(
        event_id=event.get("id"),
        kickoff_utc=kickoff,
        home=home,
        away=away,
        state=status.get("state", "pre"),
        status_detail=status.get("shortDetail", ""),
    )


def games_on(local_date, tz):
    """Every NFL game that kicks off on `local_date` in timezone `tz`.

    A Monday night game kicks off at 00:15Z Tuesday, so asking ESPN for a single
    calendar day would miss it. We fetch a three-day window and filter by the
    kickoff's date in the user's own timezone instead.
    """
    start = local_date - datetime.timedelta(days=1)
    end = local_date + datetime.timedelta(days=1)
    url = "%s?limit=100&dates=%s-%s" % (
        SCOREBOARD,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
    )

    payload = get_json(url)
    found = []
    for event in payload.get("events", []):
        try:
            game = _parse_event(event)
        except (KeyError, IndexError, ValueError):
            continue  # Malformed event; a missing game beats a crashed report.
        if game.kickoff_utc.astimezone(tz).date() == local_date:
            found.append(game)

    found.sort(key=lambda g: g.kickoff_utc)
    return found


def games_in_week(season, week, tz):
    """Every game in a fantasy week, grouped by the local date it falls on.

    Returns [(date, [Game, ...]), ...] in calendar order. A week spans Thursday
    to Monday, and occasionally a Wednesday opener.
    """
    url = "%s?limit=100&week=%d&seasontype=2&dates=%s" % (SCOREBOARD, int(week), season)
    payload = get_json(url)

    by_day = {}
    for event in payload.get("events", []):
        try:
            game = _parse_event(event)
        except (KeyError, IndexError, ValueError):
            continue
        local_date = game.kickoff_utc.astimezone(tz).date()
        by_day.setdefault(local_date, []).append(game)

    days = []
    for local_date in sorted(by_day):
        games = sorted(by_day[local_date], key=lambda g: g.kickoff_utc)
        days.append((local_date, games))
    return days


def index_by_team(games):
    """Map each participating team abbreviation to its game."""
    lookup = {}
    for game in games:
        lookup[game.home] = game
        lookup[game.away] = game
    return lookup
