"""Estimating a matchup's win probability for platforms that publish none.

ESPN publishes its own number and that is always preferred. Sleeper publishes
none - not in its REST API, and no field anywhere in its GraphQL schema - so
this stands in for Sleeper leagues.

Sleeper has never described their method publicly. What they have said is that
they rebuilt it in 2022 to avoid large swings and premature "certain victory"
calls, which is the one design constraint reflected here: the spread never
collapses to zero while games are still being played, so the number moves
steadily rather than snapping to 0% or 100%.

The per-position constants below are not guesses. They were fitted against
Sleeper's own published projections and results for the 2025 regular season -
4,933 player-weeks - by comparing what Sleeper projected with what actually
happened:

    position   bias    sigma at a 10-point projection
    QB        -2.72    7.5
    RB        -0.36    6.2
    WR        -0.56    6.5
    TE        -0.04    6.4
    K         -0.20    4.8
    DEF       +0.15    6.7

Two findings drive the model. Sleeper over-projects quarterbacks by about 2.7
points a week, consistently, and it is not an artifact of players who never
took the field. And spread grows with the size of the projection: a back
projected for 20 is far less predictable in absolute terms than one projected
for 5. Both are corrected for here.
"""

import math

# bias: mean of (actual - projected). sd = sd_base + sd_slope * projection.
# Fitted on the 2025 regular season, non-appearances included so that the risk
# of a late scratch stays in the spread.
PLAYER_MODEL = {
    "QB":  {"bias": -2.72, "sd_base": 7.33, "sd_slope": 0.017},
    "RB":  {"bias": -0.36, "sd_base": 2.88, "sd_slope": 0.329},
    "WR":  {"bias": -0.56, "sd_base": 3.26, "sd_slope": 0.321},
    "TE":  {"bias": -0.04, "sd_base": 3.09, "sd_slope": 0.328},
    "K":   {"bias": -0.20, "sd_base": 4.29, "sd_slope": 0.049},
    "DEF": {"bias":  0.15, "sd_base": 4.06, "sd_slope": 0.268},
}
FALLBACK = {"bias": -0.4, "sd_base": 3.4, "sd_slope": 0.3}

# Floor on the combined spread while anything is unfinished. Without it a
# handful of nearly-over games would produce a 0% or 100% that a single late
# touchdown could overturn.
MIN_TOTAL_SD = 3.0

# Never show absolute certainty until every game has actually ended.
MAX_CONFIDENCE = 0.99


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def forecast(position, projection, actual, fraction_remaining):
    """One starter's expected final score and the spread around it.

    Returns (expected_points, standard_deviation). A finished player is a known
    quantity: their score, with no spread left.
    """
    points = float(actual or 0.0)
    left = max(0.0, min(float(fraction_remaining or 0.0), 1.0))
    if left <= 0.0:
        return points, 0.0

    model = PLAYER_MODEL.get(position) or FALLBACK
    projected = float(projection or 0.0)

    # Correct the projection for the platform's measured bias, then count only
    # the share of it still to be earned.
    adjusted = max(0.0, projected + model["bias"])
    expected = points + adjusted * left

    # Variance accumulates with playing time, so the spread shrinks with the
    # square root of what is left.
    full_sd = model["sd_base"] + model["sd_slope"] * max(projected, 0.0)
    return expected, full_sd * math.sqrt(left)


def matchup(my_starters, their_starters):
    """Win probability for one head-to-head matchup.

    Each starter needs `position`, `projection`, `points` and
    `fraction_remaining`. Returns a dict with the probability, both projected
    finals, and how much is still undecided.
    """
    def side(starters):
        total = 0.0
        variance = 0.0
        for player in starters:
            expected, sd = forecast(
                player.get("position"), player.get("projection"),
                player.get("points"), player.get("fraction_remaining"))
            total += expected
            variance += sd * sd
        return total, variance

    my_total, my_variance = side(my_starters)
    their_total, their_variance = side(their_starters)

    variance = my_variance + their_variance
    settled = variance <= 0.0

    if settled:
        if my_total > their_total:
            probability = 1.0
        elif my_total < their_total:
            probability = 0.0
        else:
            probability = 0.5
    else:
        spread = max(math.sqrt(variance), MIN_TOTAL_SD)
        probability = normal_cdf((my_total - their_total) / spread)
        probability = min(max(probability, 1.0 - MAX_CONFIDENCE), MAX_CONFIDENCE)

    return {
        "probability": probability,
        "my_projected": my_total,
        "their_projected": their_total,
        "spread": 0.0 if settled else math.sqrt(variance),
        "settled": settled,
    }
