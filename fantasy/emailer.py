"""The emailed version of the daily rundown.

Mail clients strip modern CSS, so this is deliberately old-fashioned: nested
tables and inline styles only, no flexbox, no grid, no stylesheet.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

COLORS = {
    "for": ("#0f9d58", "#eaf7f0"),
    "against": ("#d92d3c", "#fdecee"),
    "both": ("#b8860b", "#fdf6e3"),
}
LABEL = {"for": "FOR ME", "against": "AGAINST", "both": "CONFLICT"}
GROUP = {"for": "For me", "both": "Conflict", "against": "Against me"}
BAD_INJURIES = ("Out", "IR", "Doubtful", "Suspended")


def _esc(text):
    return (str(text if text is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _entries_html(entries, is_opponent, color):
    if not entries:
        return '<div style="color:#9aa2b0;font-size:12px;">&mdash;</div>'
    rows = []
    for entry in entries:
        faded = "opacity:.55;" if not entry.get("starting") else ""
        opponent = ""
        if is_opponent and entry.get("opponent"):
            opponent = ' <span style="color:#7b8494;">&middot; %s</span>' % _esc(entry["opponent"])
        rows.append(
            '<div style="font-size:12px;line-height:1.5;%s">'
            '<strong>%s</strong> '
            '<span style="background:#e8ebf0;border-radius:3px;padding:1px 5px;'
            'font-size:11px;font-weight:700;">%s</span>%s</div>'
            % (faded, _esc(entry["league"]), _esc(entry["slot"]), opponent))
    return "".join(rows)


def _player_html(player):
    border, background = COLORS.get(player["verdict"], ("#888", "#f4f4f4"))

    injury = ""
    if player.get("injury_status"):
        bad = player["injury_status"] in BAD_INJURIES
        injury = (
            '<span style="background:%s;color:%s;font-size:11px;font-weight:700;'
            'padding:2px 6px;border-radius:4px;margin-left:6px;">%s%s</span>'
            % ("#fdecee" if bad else "#fff4e0",
               "#d92d3c" if bad else "#b26b00",
               _esc(player["injury_status"]),
               " &middot; " + _esc(player["injury_body_part"])
               if player.get("injury_body_part") else ""))

    score = ""
    if player.get("game_state") not in (None, "pre") and player.get("score_label"):
        score = ('<span style="float:right;font-size:14px;font-weight:700;'
                 'color:#12151b;">%s</span>' % _esc(player["score_label"]))

    return """
  <table role="presentation" width="100%%" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse;margin-bottom:8px;background:%s;
                border:1px solid #e0e4ea;border-radius:8px;">
    <tr>
      <td width="4" style="background:%s;font-size:0;line-height:0;">&nbsp;</td>
      <td style="padding:9px 12px;font-family:-apple-system,Segoe UI,Arial,sans-serif;">
        <div>
          <strong style="font-size:15px;color:#12151b;">%s</strong>
          <span style="color:#5f6877;font-size:12px;">&nbsp;%s &middot; %s</span>
          <span style="float:right;color:%s;font-size:10px;font-weight:800;">%s</span>
        </div>
        <div style="color:#5f6877;font-size:12px;margin-top:3px;">%s &middot; %s%s%s</div>
        <table role="presentation" width="100%%" cellpadding="0" cellspacing="0"
               style="margin-top:8px;border-collapse:separate;border-spacing:5px 0;">
          <tr valign="top">
            <td width="50%%" style="background:#f4f6f9;border-radius:6px;padding:6px 8px;">
              <div style="font-size:9px;font-weight:800;letter-spacing:.06em;
                          color:#0f9d58;text-transform:uppercase;">For me</div>%s
            </td>
            <td width="50%%" style="background:#f4f6f9;border-radius:6px;padding:6px 8px;">
              <div style="font-size:9px;font-weight:800;letter-spacing:.06em;
                          color:#d92d3c;text-transform:uppercase;">Against me</div>%s
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>""" % (
        background, border,
        _esc(player["name"]), _esc(player["position"]), _esc(player["team"]),
        border, LABEL.get(player["verdict"], ""),
        _esc(player["kickoff_label"]), _esc(player["matchup"]), injury, score,
        _entries_html(player["for_me"], False, "#0f9d58"),
        _entries_html(player["against_me"], True, "#d92d3c"))


def build_html(day, week, change_lines=None, app_url=None):
    """The full HTML body for one game day."""
    counts = day["counts"]

    changes = ""
    if change_lines:
        items = "".join(
            '<div style="font-size:12px;line-height:1.6;">%s</div>' % _esc(line)
            for line in change_lines)
        changes = (
            '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
            'style="margin-bottom:14px;background:#fdf6e3;border:1px solid #d4a017;'
            'border-radius:8px;"><tr><td style="padding:10px 12px;'
            'font-family:-apple-system,Segoe UI,Arial,sans-serif;">'
            '<div style="font-size:10px;font-weight:800;letter-spacing:.07em;'
            'color:#b8860b;text-transform:uppercase;margin-bottom:5px;">'
            'Lineup changes</div>%s</td></tr></table>' % items)

    body = []
    multiple_waves = len(set(p.get("wave", 0) for p in day["players"])) > 1
    last_wave, last_verdict = None, None
    for player in day["players"]:
        if multiple_waves and player.get("wave") != last_wave:
            in_wave = [p for p in day["players"]
                       if p.get("wave") == player.get("wave")]
            times = []
            for p in in_wave:
                if p["kickoff_label"] not in times:
                    times.append(p["kickoff_label"])
            body.append(
                '<div style="margin:20px 0 4px;padding:7px 10px;border-radius:6px;'
                'background:#eef1f5;border:1px solid #e0e4ea;font-size:13px;'
                'font-weight:700;color:#12151b;">%s '
                '<span style="color:#5f6877;font-weight:600;">&middot; %s &middot; %d</span>'
                '</div>' % (_esc(player.get("wave_name", "")),
                            _esc(" &amp; ".join(times)), len(in_wave)))
            last_wave = player.get("wave")
            last_verdict = None
        if player["verdict"] != last_verdict:
            colour = COLORS.get(player["verdict"], ("#5f6877", ""))[0]
            scope = ([p for p in day["players"]
                      if p.get("wave") == player.get("wave")]
                     if multiple_waves else day["players"])
            count = len([p for p in scope
                         if p["verdict"] == player["verdict"]])
            body.append(
                '<div style="font-size:11px;font-weight:800;letter-spacing:.07em;'
                'color:%s;text-transform:uppercase;margin:16px 0 7px;">%s &middot; %d</div>'
                % (colour, _esc(GROUP.get(player["verdict"], "")), count))
            last_verdict = player["verdict"]
        body.append(_player_html(player))

    if not day["players"]:
        body.append('<div style="color:#5f6877;font-size:14px;padding:20px 0;">'
                    'No rostered players are in today\'s games.</div>')

    link = ""
    if app_url:
        link = ('<div style="margin-top:20px;text-align:center;">'
                '<a href="%s" style="background:#0f9d58;color:#fff;font-size:14px;'
                'font-weight:600;text-decoration:none;padding:10px 18px;'
                'border-radius:8px;display:inline-block;">Open Fantasy Tracker</a></div>'
                % _esc(app_url))

    return """<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f6f9;">
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0"
       style="background:#f4f6f9;padding:16px 10px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0"
           style="max-width:600px;width:100%%;">
      <tr><td style="font-family:-apple-system,Segoe UI,Arial,sans-serif;padding-bottom:10px;">
        <div style="font-size:21px;font-weight:700;color:#12151b;">%s</div>
        <div style="color:#5f6877;font-size:13px;margin-top:2px;">
          Week %s &middot; %d game%s &middot; %d player%s
        </div>
        <div style="margin-top:9px;font-size:12px;">
          <span style="color:#0f9d58;font-weight:700;">%d for you</span> &nbsp;
          <span style="color:#d92d3c;font-weight:700;">%d against you</span> &nbsp;
          <span style="color:#b8860b;font-weight:700;">%d conflict</span>
        </div>
      </td></tr>
      <tr><td>%s%s%s</td></tr>
      <tr><td style="font-family:-apple-system,Segoe UI,Arial,sans-serif;
                     color:#9aa2b0;font-size:11px;text-align:center;padding-top:22px;">
        Fantasy Tracker
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>""" % (
        _esc(day["date_label"]), _esc(week),
        len(day["games"]), "" if len(day["games"]) == 1 else "s",
        counts["total"], "" if counts["total"] == 1 else "s",
        counts["for"], counts["against"], counts["both"],
        changes, "".join(body), link)


def build_text(day, week, change_lines=None):
    lines = ["%s - Week %s" % (day["date_label"], week),
             "%d for you, %d against you, %d conflicted" % (
                 day["counts"]["for"], day["counts"]["against"],
                 day["counts"]["both"]), ""]
    for player in day["players"]:
        bits = ["%-9s %-22s %-3s %-4s %s" % (
            LABEL.get(player["verdict"], ""), player["name"], player["position"],
            player["team"], player["kickoff_label"])]
        if player["injury_status"]:
            bits.append("(%s)" % player["injury_status"])
        lines.append(" ".join(bits))
    if change_lines:
        lines += ["", "Lineup changes:"] + ["  * %s" % c for c in change_lines]
    return "\n".join(lines)


def send(subject, html, text, config=None):
    """Send via SMTP. Returns (sent, error)."""
    config = config or {}
    host = config.get("host") or os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(config.get("port") or os.environ.get("SMTP_PORT") or 587)
    user = (config.get("user") or os.environ.get("SMTP_USER") or "").strip()
    # Google shows app passwords as four spaced groups ("abcd efgh ijkl mnop")
    # but rejects the spaces, so strip all whitespace rather than making the
    # user notice that themselves.
    password = "".join(
        (config.get("password") or os.environ.get("SMTP_PASSWORD") or "").split())
    to_address = (config.get("to") or os.environ.get("EMAIL_TO") or user).strip()
    from_address = (config.get("sender") or os.environ.get("EMAIL_FROM")
                    or user).strip()

    if not user or not password or not to_address:
        return False, "Email is not configured (SMTP_USER / SMTP_PASSWORD / EMAIL_TO)."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("Fantasy Tracker", from_address))
    message["To"] = to_address
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.send_message(message)
        return True, None
    except smtplib.SMTPAuthenticationError as exc:
        return False, (
            "Email rejected the login (%s). Gmail needs a 16-character app "
            "password from myaccount.google.com/apppasswords, not the account "
            "password, and 2-Step Verification must be on." % exc.smtp_code)
    except (smtplib.SMTPException, OSError) as exc:
        return False, "Email failed: %s" % exc
