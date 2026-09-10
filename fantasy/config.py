"""Loading and validating config.json."""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_DIR = os.path.join(ROOT, "data")

DEFAULTS = {
    "timezone": "America/Chicago",
    "include_my_bench": True,
    "include_opponent_bench": False,
    "sleeper": {"username": ""},
    "espn": {"espn_s2": "", "swid": "", "league_ids": [], "auto_discover": True},
}


class ConfigError(Exception):
    pass


def _merge(base, override):
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _flag(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def from_env():
    """Build a config from environment variables.

    GitHub Actions has no config.json - credentials arrive as repository
    secrets instead.
    """
    username = (os.environ.get("SLEEPER_USERNAME") or "").strip()
    espn_s2 = (os.environ.get("ESPN_S2") or "").strip()
    swid = (os.environ.get("ESPN_SWID") or "").strip()
    if not username and not espn_s2:
        return None

    raw_ids = (os.environ.get("ESPN_LEAGUE_IDS") or "").strip()
    league_ids = [part.strip() for part in raw_ids.replace(",", " ").split() if part.strip()]

    return {
        "timezone": (os.environ.get("TIMEZONE") or "America/Chicago").strip(),
        "include_my_bench": _flag("INCLUDE_MY_BENCH", True),
        "include_opponent_bench": _flag("INCLUDE_OPPONENT_BENCH", False),
        "sleeper": {"username": username},
        "espn": {
            "espn_s2": espn_s2,
            "swid": swid,
            "league_ids": league_ids,
            "auto_discover": _flag("ESPN_AUTO_DISCOVER", True),
        },
    }


def load(path=None):
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        env_config = from_env()
        if env_config:
            return _merge(DEFAULTS, env_config)
        raise ConfigError(
            "No config.json found at %s.\nRun:  python3 setup_wizard.py" % path
        )
    with open(path, "r") as handle:
        try:
            raw = json.load(handle)
        except ValueError as exc:
            raise ConfigError("config.json is not valid JSON: %s" % exc)

    config = _merge(DEFAULTS, raw)

    has_sleeper = bool((config["sleeper"] or {}).get("username"))
    espn = config["espn"] or {}
    has_espn = bool(espn.get("espn_s2") and espn.get("swid"))
    if not has_sleeper and not has_espn:
        raise ConfigError(
            "config.json needs at least a Sleeper username or ESPN cookies."
        )
    return config


def save(config, path=None):
    path = path or CONFIG_PATH
    with open(path, "w") as handle:
        json.dump(config, handle, indent=2)
    os.chmod(path, 0o600)  # Contains ESPN session cookies.
