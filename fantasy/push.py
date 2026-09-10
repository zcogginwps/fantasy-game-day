"""Sending web push notifications.

Signing a push needs real crypto, so this is the one part of the project with a
third-party dependency (`pywebpush`). It only runs in GitHub Actions, where the
dependency is installed from requirements.txt - the local tools stay
dependency-free.
"""

import json
import os

VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT") or "mailto:noreply@example.com"


class PushUnavailable(Exception):
    """pywebpush is not installed, so nothing can be sent."""


def _webpush():
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        raise PushUnavailable(
            "pywebpush is not installed. Run: pip3 install -r requirements.txt")
    return webpush, WebPushException


def load_subscriptions(raw=None):
    """Parse the stored subscription(s).

    Accepts a single subscription object or a list, so more phones can be added
    later without changing the format.
    """
    raw = raw if raw is not None else os.environ.get("PUSH_SUBSCRIPTION", "")
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [s for s in parsed if isinstance(s, dict) and s.get("endpoint")]


def send(title, body, url=None, tag="gameday", private_key=None, subscriptions=None):
    """Push one notification to every registered device.

    Returns (delivered, [error, ...]). A subscription that has expired reports
    410 Gone; that phone simply needs to re-enable notifications.
    """
    webpush, WebPushException = _webpush()

    private_key = private_key or os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not private_key:
        raise PushUnavailable("No VAPID_PRIVATE_KEY is set.")

    subscriptions = subscriptions if subscriptions is not None else load_subscriptions()
    if not subscriptions:
        return 0, ["No push subscription is registered yet."]

    payload = json.dumps({"title": title, "body": body,
                          "url": url or "./", "tag": tag})

    delivered = 0
    errors = []
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=3600,
            )
            delivered += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                errors.append(
                    "A device's subscription has expired - re-enable "
                    "notifications on that phone.")
            else:
                errors.append("Push failed (%s): %s" % (status or "?", exc))
        except Exception as exc:  # noqa: BLE001 - never let a push break the run
            errors.append("Push failed: %s" % exc)

    return delivered, errors
