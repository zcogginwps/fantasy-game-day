"""Tiny HTTP helper built on the standard library only.

Everything here avoids third-party packages on purpose: the whole point is that
this runs on a stock macOS Python with nothing to install first.
"""

import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")

# ESPN's public scoreboard endpoint 403s on any User-Agent it does not
# recognise - including browser-shaped ones and our own custom string - but
# accepts urllib's stock header. So we send no User-Agent unless a caller asks
# for a specific one.


class FetchError(Exception):
    """Raised when a request fails after all retries."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def get_json(url, headers=None, cookies=None, retries=3, timeout=30, user_agent=None):
    """GET a URL and parse the response as JSON, retrying on transient errors."""
    req_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip",
    }
    if user_agent:
        req_headers["User-Agent"] = user_agent
    if headers:
        req_headers.update(headers)
    if cookies:
        req_headers["Cookie"] = "; ".join(
            "%s=%s" % (k, v) for k, v in cookies.items() if v
        )

    last_error = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 4xx responses are our fault (bad league id, expired cookies) and
            # retrying will not change the answer.
            if exc.code < 500 and exc.code != 429:
                raise FetchError("HTTP %d for %s" % (exc.code, url), status=exc.code)
            last_error = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(1.5 * (attempt + 1))

    raise FetchError("Failed after %d attempts: %s (%s)" % (retries, url, last_error))


def get_json_cached(url, max_age_seconds, cache_key, **kwargs):
    """Same as get_json, but reuse a recent copy from disk when one exists.

    Used for the 14MB Sleeper player dictionary, which changes at most daily but
    would otherwise be re-downloaded on every single run.
    """
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    path = os.path.join(CACHE_DIR, cache_key + ".json")

    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_seconds:
        try:
            with open(path, "r") as handle:
                return json.load(handle)
        except (ValueError, IOError):
            pass  # Corrupt or half-written cache: fall through and refetch.

    data = get_json(url, **kwargs)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)
    return data
