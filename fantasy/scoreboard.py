"""The week's head-to-head matchups, one per league.

Win probability is not evenly available. ESPN publishes one per matchup side and
that is used as-is. Sleeper publishes none anywhere - not in its REST API, and
no field in its GraphQL schema - and its projected-points query needs an account
token, so for Sleeper leagues this estimates one from Sleeper's own public
per-player projections. Estimates are marked as such so they are never mistaken
for the platform's own number.
"""

import math

from . import sleeper as sleeper_client

# Rough weekly spread of a single fantasy starter's score, in points. Used only
# to spread the projected margin into a probability.
PLAYER_SIGMA = 7.5


def _normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _finished(game):
    return bool(game) and game.get("state") == "post"


def _started(game):
    return bool(game) and game.get("state") in ("in", "post")


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
                    "kickoff_label": "", "matchup": ""}

        id_source = league.get("id_source") or league["platform"]
        record = self.assembler.record_for(id_source, player_id, league)
        if not record:
            return {"name": "Unknown", "position": "", "team": None, "slot": slot,
                    "points": points, "projection": None, "game_state": None,
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


def _project_side(side):
    """Where this team is heading: points already banked plus what is left.

    A finished player contributes what they actually scored. Anyone still to
    play, or mid-game, contributes the better of their score so far and their
    projection.
    """
    total = 0.0
    unsettled = 0
    for player in side["starters"]:
        points = player.get("points") or 0.0
        projection = player.get("projection")
        if _finished(_game_stub(player)):
            total += points
            continue
        unsettled += 1
        total += max(points, projection or 0.0)
    return total, unsettled


def _game_stub(player):
    state = player.get("game_state")
    return {"state": state} if state else None


def _estimate_probability(my_projected, their_projected, unsettled):
    """A win probability for platforms that do not publish one."""
    if unsettled <= 0:
        if my_projected == their_projected:
            return 0.5
        return 1.0 if my_projected > their_projected else 0.0
    sigma = PLAYER_SIGMA * math.sqrt(unsettled)
    return _normal_cdf((my_projected - their_projected) / sigma)


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


def build(leagues, resolver):
    """One scoreboard entry per league the user has a matchup in."""
    entries = []

    for league in leagues:
        raw = league.get("matchup")
        if not raw or not raw.get("opponents"):
            continue

        me = _build_side(league, raw["me"], resolver)
        opponent = _build_side(league, raw["opponents"][0], resolver)

        my_projection, my_left = _project_side(me)
        their_projection, their_left = _project_side(opponent)
        unsettled = my_left + their_left

        if me["win_probability"] is not None:
            probability = float(me["win_probability"])
            source = league["platform"]
        else:
            probability = _estimate_probability(
                my_projection, their_projection, unsettled)
            source = "estimated"

        # ESPN publishes its own projection; Sleeper's is computed here. Round
        # both, since ESPN's arrives with a dozen decimal places.
        me["projected"] = round(
            my_projection if me["projected"] is None else float(me["projected"]), 1)
        opponent["projected"] = round(
            their_projection if opponent["projected"] is None
            else float(opponent["projected"]), 1)
        me["points"] = None if me["points"] is None else round(float(me["points"]), 1)
        opponent["points"] = (None if opponent["points"] is None
                              else round(float(opponent["points"]), 1))

        played = sum(1 for s in me["starters"] + opponent["starters"]
                     if _started(_game_stub(s)))
        entries.append({
            "league": league["league_name"],
            "platform": league["platform"],
            "me": me,
            "opponent": opponent,
            "win_probability": round(probability, 3),
            "win_probability_source": source,
            "starters_played": played,
            "starters_total": len(me["starters"]) + len(opponent["starters"]),
            "in_progress": played > 0 and unsettled > 0,
        })

    entries.sort(key=lambda e: e["league"])
    return entries
