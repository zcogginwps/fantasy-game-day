"""NFL team abbreviation normalisation.

Sleeper and ESPN mostly agree, but not entirely: Sleeper says WAS and still
carries the legacy OAK code, while ESPN says WSH. Everything downstream works in
one canonical vocabulary so a player's team always matches their game.
"""

# Canonical form is ESPN's, because the game schedule comes from ESPN.
_ALIASES = {
    "WAS": "WSH",
    "WSH": "WSH",
    "OAK": "LV",
    "LV": "LV",
    "LVR": "LV",
    "JAC": "JAX",
    "JAX": "JAX",
    "LA": "LAR",
    "SD": "LAC",
    "STL": "LAR",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
}


def normalize(abbr):
    """Return the canonical abbreviation for an NFL team code."""
    if not abbr:
        return None
    key = str(abbr).strip().upper()
    return _ALIASES.get(key, key)
