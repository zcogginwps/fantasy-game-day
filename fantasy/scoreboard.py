"""The week's head-to-head matchups, one per league.

Win probability is not evenly available. ESPN publishes one per matchup side and
that is used as-is. Sleeper publishes none anywhere - not in its REST API, and
no field in its GraphQL schema - and its projected-points query needs an account
token, so for Sleeper leagues this estimates one from Sleeper's own public
per-player projections. Estimates are marked as such so they are never mistaken
for the platform's own number.
"""

from . import winprob


def _started(player):
    return (player.get("game_state") or "") in ("in", "post")


class Resolver(object):
    """Turns platform-local player ids into displayable player rows."""

    def __init__(self, assembler, games_by_team, projections, tz):
        self.assembler = assembler
        self.games_by_team = games_by_team
        self.projections = projections
        self.tz = tz

    def player(self, league, player_id, slot, points):
        if not player_id:
            return {"name": "Empty", "position": "", "team": None, "slot": slot,
                    "points": None, "projection": None, "game_state": None,
                    "fraction_remaining": 0.0,
                    "kickoff_label": "", "matchup": ""}

        id_source = league.get("id_source") or league["platform"]
        record = self.assembler.record_for(id_source, player_id, league)
        if not record:
            return {"name": "Unknown", "position": "", "team": None, "slot": slot,
                    "points": points, "projection": None, "game_state": None,
                    "fraction_remaining": 0.0,
                    "kickoff_label": "", "matchup": ""}

        team = record.get("team")
        game = self.games_by_team.get(team)
        game_dict = game.to_dict(self.tz) if game else None

        return {
            "name": record["name"],
            "position": record.get("position") or "",
            "team": team,
            "slot": slot,
            "points": points,
            "projection": self.projection_for(league, player_id, record),
            "injury_status": record.get("injury_status") or "",
            "game_state": game_dict["state"] if game_dict else None,
            # 1.0 before kickoff, 0.0 once final - drives the forecast.
            "fraction_remaining": (game.fraction_remaining() if game else 0.0),
            "kickoff_label": game_dict["kickoff_label"] if game_dict else "",
            "matchup": ("%s %s" % ("vs" if game.is_home(team) else "@",
                                   game.opponent_of(team))) if game else "",
        }

    def projection_for(self, league, player_id, record):
        """Sleeper's published projection, in this league's scoring flavour."""
        if not self.projections:
            return None
        key = player_id
        if (league.get("id_source") or league["platform"]) != "sleeper":
            # ESPN ids have to be mapped back through Sleeper's player index.
            key = self.assembler.by_espn_id.get(str(player_id))
            if not key and record.get("espn_id"):
                key = self.assembler.by_espn_id.get(str(record["espn_id"]))
        row = self.projections.get(str(key or ""))
        if not row:
            return None
        return row.get(league.get("scoring_type") or "pts_ppr")


def _build_side(league, raw_side, resolver):
    starters = [
        resolver.player(league, entry.get("player_id"), entry.get("slot"),
                        entry.get("points"))
        for entry in raw_side.get("starters") or []
    ]
    return {
        "name": raw_side.get("name") or "Team",
        "points": raw_side.get("points"),
        "projected": raw_side.get("projected"),
        "win_probability": raw_side.get("win_probability"),
        "starters": starters,
    }


def build(leagues, resolver, week=None, current_week=None):
    """One scoreboard entry per league the user has a matchup in.

    `week` and `current_week` decide how much can honestly be shown. Both
    platforms only report live scoring for the week actually being played:
    ESPN's applied totals are always the current period whatever week is asked
    for, and Sleeper publishes projections for only a few hundred players
    beyond the current week. So scores and probabilities are shown for the
    current week, and a future week shows the fixture alone.
    """
    entries = []
    if week is None or current_week is None:
        week_state = "current"
    elif int(week) > int(current_week):
        week_state = "upcoming"
    elif int(week) < int(current_week):
        week_state = "past"
    else:
        week_state = "current"

    for league in leagues:
        raw = league.get("matchup")
        if not raw or not raw.get("opponents"):
            continue

        me = _build_side(league, raw["me"], resolver)
        opponent = _build_side(league, raw["opponents"][0], resolver)

        if week_state != "current":
            # Per-player points for another week would be this week's numbers
            # wearing the wrong label, so they are cleared rather than shown.
            for player in me["starters"] + opponent["starters"]:
                player["points"] = None
                player["game_state"] = None

        if week_state == "upcoming":
            entries.append({
                "league": league["league_name"],
                "platform": league["platform"],
                "me": me,
                "opponent": opponent,
                "win_probability": None,
                "win_probability_source": "unavailable",
                "week_state": week_state,
                "starters_played": 0,
                "starters_total": len(me["starters"]) + len(opponent["starters"]),
                "in_progress": False,
            })
            me["points"] = None
            opponent["points"] = None
            me["projected"] = None
            opponent["projected"] = None
            continue

        forecast = winprob.matchup(me["starters"], opponent["starters"])

        if me["win_probability"] is not None:
            # The platform publishes its own; always prefer it.
            probability = float(me["win_probability"])
            source = league["platform"]
            me["projected"] = round(float(me["projected"]), 1)
            opponent["projected"] = round(float(opponent["projected"]), 1)
        else:
            probability = forecast["probability"]
            source = "estimated"
            # Show the same projected finals the probability was derived from,
            # rather than a raw projection total that would disagree with it.
            me["projected"] = round(forecast["my_projected"], 1)
            opponent["projected"] = round(forecast["their_projected"], 1)
        me["points"] = None if me["points"] is None else round(float(me["points"]), 1)
        opponent["points"] = (None if opponent["points"] is None
                              else round(float(opponent["points"]), 1))

        played = sum(1 for s in me["starters"] + opponent["starters"]
                     if _started(s))
        unsettled = sum(1 for s in me["starters"] + opponent["starters"]
                        if (s.get("fraction_remaining") or 0.0) > 0.0)
        entries.append({
            "league": league["league_name"],
            "platform": league["platform"],
            "me": me,
            "opponent": opponent,
            "win_probability": round(probability, 3),
            "win_probability_source": source,
            "week_state": week_state,
            "starters_played": played,
            "starters_total": len(me["starters"]) + len(opponent["starters"]),
            "in_progress": played > 0 and unsettled > 0,
        })

    entries.sort(key=lambda e: e["league"])
    return entries
