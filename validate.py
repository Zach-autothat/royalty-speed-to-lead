"""Run Speed-to-Lead against real GHL data and print a readable report.

Usage:
  python3 validate.py 7d
  python3 validate.py 14d
  python3 validate.py 30d
  python3 validate.py all
"""
import sys
import time

import business_hours as bh
from ghl_client import GHLClient
import speed_to_lead as stl

DAY_MS = 86_400_000


def window_for(arg):
    now = int(time.time() * 1000)
    if arg == "all":
        return 0, now, "all time"
    n = int(arg.rstrip("d"))
    return now - n * DAY_MS, now, f"last {n} days"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "7d"
    start, end, label = window_for(arg)

    client = GHLClient()
    print(f"Fetching leads for {label} …", flush=True)
    t0 = time.time()
    leads = stl.compute_leads(start, end, client=client)
    names = client.users()
    agg = stl.aggregate(leads, names)
    secs = time.time() - t0

    t = agg["totals"]
    print(f"\n=== SPEED TO LEAD — {label} ===  ({secs:.1f}s, {len(leads)} leads)\n")
    if not leads:
        print("No new contacts in this window.")
        return
    print(f"Leads:          {t['leads']}")
    print(f"Responded:      {t['responded']}  ({(t['response_rate'] or 0)*100:.0f}%)")
    print(f"No response:    {t['no_response']}")
    print(f"Median (raw):   {bh.fmt_duration(t['raw']['median'])}")
    print(f"Median (bizhrs):{bh.fmt_duration(t['bh']['median'])}")
    print(f"Avg    (bizhrs):{bh.fmt_duration(t['bh']['avg'])}")

    print("\n--- Per rep (sorted by fastest business-hours median) ---")
    hdr = f"{'Rep':<22}{'Leads':>6}{'Resp':>6}{'NoResp':>7}{'Med raw':>12}{'Med bizhrs':>13}"
    print(hdr)
    print("-" * len(hdr))
    for r in agg["per_rep"]:
        print(f"{r['rep_name'][:21]:<22}{r['leads']:>6}{r['responded']:>6}{r['no_response']:>7}"
              f"{bh.fmt_duration(r['raw']['median']):>12}{bh.fmt_duration(r['bh']['median']):>13}")

    print("\n--- Lead arrival by hour (business tz) ---")
    peak = max((h['leads'] for h in agg['heatmap']), default=0) or 1
    for h in agg["heatmap"]:
        if h["leads"] == 0:
            continue
        bar = "#" * int(round(20 * h["leads"] / peak))
        print(f"{h['hour']:02d}:00  {h['leads']:>4}  {bar}  med {bh.fmt_duration(h['median_bh_seconds'])}")


if __name__ == "__main__":
    main()
