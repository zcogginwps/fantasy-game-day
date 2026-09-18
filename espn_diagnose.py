#!/usr/bin/env python3
"""Print what ESPN actually returns for one league, one week.

Temporary: run from CI, where ESPN is reachable and the cookies live as
secrets. Prints no credentials - only league ids, player names and points.
"""

import json
import os
import sys

from fantasy import config as config_module
from fantasy import espn, sleeper
from fantasy.webreq import get_json

conf = config_module.from_env()
if not conf:
    sys.exit("No config in env.")

espn_conf = conf["espn"]
season = sleeper.get_state().get("season") or "2026"
week = int(sleeper.get_state().get("week") or 1)
print("season=%s  sleeper_week=%s" % (season, week))

league_ids = espn_conf.get("league_ids") or espn.discover_leagues(espn_conf, season)
print("league_ids=%s" % league_ids)
if not league_ids:
    sys.exit("No ESPN leagues.")

league_id = league_ids[0]
cookies, swid = espn._cookies(espn_conf)

for label, url in (
    ("WITHOUT scoringPeriodId",
     "%s/%s/segments/0/leagues/%s?view=mRoster&view=mMatchup&view=mMatchupScore&view=mTeam&view=mSettings"
     % (espn.LEAGUE_BASE, season, league_id)),
    ("WITH scoringPeriodId=%d" % week,
     "%s/%s/segments/0/leagues/%s?view=mRoster&view=mMatchup&view=mMatchupScore&view=mTeam&view=mSettings&scoringPeriodId=%d"
     % (espn.LEAGUE_BASE, season, league_id, week)),
):
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    payload = get_json(url, cookies=cookies)
    print("top-level scoringPeriodId = %r" % payload.get("scoringPeriodId"))

    my_team = None
    for team in payload.get("teams") or []:
        if swid and swid in [str(o) for o in (team.get("owners") or [])]:
            my_team = team
            break
    if my_team is None:
        print("!! my team not found")
        continue

    shown = 0
    for entry in (my_team.get("roster") or {}).get("entries") or []:
        if entry.get("lineupSlotId") in espn.BENCH_SLOTS:
            continue
        pool = entry.get("playerPoolEntry") or {}
        player = pool.get("player") or {}
        print("\n  %s  (slot %s)" % (player.get("fullName"), entry.get("lineupSlotId")))
        print("    pool.appliedStatTotal = %r" % pool.get("appliedStatTotal"))
        stats = player.get("stats") or []
        print("    player.stats entries (%d):" % len(stats))
        for st in stats[:8]:
            print("      scoringPeriodId=%-3s statSourceId=%-2s statSplitTypeId=%-3s appliedTotal=%r" % (
                st.get("scoringPeriodId"), st.get("statSourceId"),
                st.get("statSplitTypeId"), st.get("appliedTotal")))
        shown += 1
        if shown >= 3:
            break
