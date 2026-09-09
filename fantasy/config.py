"""Loading and validating config.json."""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_DIR = os.path.join(ROOT, "data")

DEFAULTS = {
    "timezone": "America/Chicago",
    "include_bench": True,
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


def load(path=None):
    path = path or CONFIG_PATH
    if not os.path.exists(path):
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
