#!/usr/bin/env python3
"""Bundle the report into one self-contained HTML file.

Useful for emailing the day's rundown, saving a snapshot, or opening the page
without running the server.

    python3 build_static.py            -> data/gameday.html
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def build(report_path=None, out_path=None):
    report_path = report_path or os.path.join(ROOT, "data", "report.json")
    out_path = out_path or os.path.join(ROOT, "data", "gameday.html")

    if not os.path.exists(report_path):
        raise SystemExit("No report yet - run: python3 collect.py")

    with open(report_path, "r") as handle:
        report = json.load(handle)
    with open(os.path.join(ROOT, "web", "index.html"), "r") as handle:
        html = handle.read()

    # </script> inside the JSON would close the tag early.
    payload = json.dumps(report).replace("</", "<\\/")
    injected = '<script>window.__REPORT__ = %s;</script>\n<script>' % payload

    marker = "<script>"
    index = html.index(marker)
    html = html[:index] + injected + html[index + len(marker):]

    with open(out_path, "w") as handle:
        handle.write(html)
    return out_path


if __name__ == "__main__":
    path = build(*(sys.argv[1:3] or []))
    print("wrote %s" % path)
