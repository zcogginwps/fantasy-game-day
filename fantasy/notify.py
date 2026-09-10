"""Local notifications for Fantasy Tracker.

Phase 1 delivers to the Mac via osascript. Phase 2 will add iOS push, which
needs HTTPS hosting; this module is the seam where that plugs in.
"""

import subprocess


def _escape(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def mac_notification(title, message, subtitle=None, sound="Ping"):
    """Post a macOS notification. Returns True if it was delivered."""
    parts = ['display notification "%s"' % _escape(message),
             'with title "%s"' % _escape(title)]
    if subtitle:
        parts.append('subtitle "%s"' % _escape(subtitle))
    if sound:
        parts.append('sound name "%s"' % _escape(sound))
    script = " ".join(parts)
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def lineup_change_alert(changes):
    """Alert for opponents shuffling their lineup."""
    opponent_changes = [c for c in changes if c["side"] == "opponent"]
    if not opponent_changes:
        return False

    from . import lineups as lineups_module
    lines = [lineups_module.describe(c) for c in opponent_changes[:3]]
    if len(opponent_changes) > 3:
        lines.append("+%d more" % (len(opponent_changes) - 3))

    return mac_notification(
        "Opponent lineup change",
        " | ".join(lines),
        subtitle="%d change%s" % (len(opponent_changes),
                                  "" if len(opponent_changes) == 1 else "s"),
    )


def kickoff_summary(game_label, players):
    """Alert as one game is about to start."""
    if not players:
        return False
    for_me = len([p for p in players if p["verdict"] in ("for", "both")])
    against = len([p for p in players if p["verdict"] in ("against", "both")])
    hurt = [p["name"] for p in players
            if p["injury_status"] in ("Out", "Doubtful", "IR", "Suspended")]

    message = "%d for you, %d against you" % (for_me, against)
    if hurt:
        message += " - OUT: %s" % ", ".join(hurt[:3])

    return mac_notification("Kickoff: %s" % game_label, message,
                            subtitle="Starting soon")
