"""Refresh the Speed-to-Lead dataset and build all outputs.

Runs the GHL compute ONCE for a window, then writes:
  out/leads.json      - per-lead dataset (the data the dashboard reads)
  out/leads.csv       - same data, spreadsheet-friendly
  out/dashboard.html  - self-contained interactive dashboard (open in a browser)

The dashboard does all date-range filtering + aggregation client-side, so the
7/14/30/all/custom toggles are instant and we only hit GHL once per refresh.

Usage:
  python3 refresh.py            # default: last 90 days
  python3 refresh.py 30d
  python3 refresh.py all
"""
import csv
import json
import os
import sys
import time

import business_hours as bh
from ghl_client import GHLClient
import speed_to_lead as stl

DAY_MS = 86_400_000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def window_for(arg):
    now = int(time.time() * 1000)
    if arg == "all":
        return 0, now, "all"
    n = int(arg.rstrip("d"))
    return now - n * DAY_MS, now, f"{n}d"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "90d"
    start, end, label = window_for(arg)
    os.makedirs(OUT, exist_ok=True)

    client = GHLClient()
    print(f"Refreshing Speed-to-Lead dataset ({label}) …", flush=True)
    t0 = time.time()
    leads = stl.compute_leads(start, end, client=client)
    names = client.users()
    for l in leads:
        l["rep_name"] = names.get(l["rep_id"], "Unassigned" if not l["rep_id"] else l["rep_id"])
    elapsed = time.time() - t0

    meta = {
        "location": "Royalty Sports Performance",
        "generated_ms": end,
        "window_days": None if label == "all" else int(label.rstrip("d")),
        "business_hours": {
            "tz": bh.config.BH_TIMEZONE,
            "open": bh.config.BH_OPEN,
            "close": bh.config.BH_CLOSE,
            "workdays": bh.config.BH_WORKDAYS,
        },
        "lead_count": len(leads),
    }
    payload = {"meta": meta, "leads": leads}

    with open(os.path.join(OUT, "leads.json"), "w") as fh:
        json.dump(payload, fh)

    # High-level summary — this is what the frontend fetches. No per-lead rows,
    # no timestamps, no PII; just aggregates per window/rep. A few KB.
    import summarize
    summary = summarize.build_summary(leads, meta, names=names)
    with open(os.path.join(OUT, "summary.json"), "w") as fh:
        json.dump(summary, fh)

    with open(os.path.join(OUT, "leads.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["contactId", "name", "rep", "anchor_ms", "response_ms",
                    "responded", "channel", "raw_seconds", "bh_seconds"])
        for l in leads:
            w.writerow([l["contactId"], l["name"], l["rep_name"], l["anchor_ms"],
                        l["response_ms"] or "", l["responded"], l["channel"] or "",
                        "" if l["raw_seconds"] is None else round(l["raw_seconds"]),
                        "" if l["bh_seconds"] is None else round(l["bh_seconds"])])

    html = DASHBOARD_HTML.replace("/*__DATA__*/", json.dumps(payload))
    with open(os.path.join(OUT, "dashboard.html"), "w") as fh:
        fh.write(html)

    print(f"Done in {elapsed:.1f}s — {len(leads)} leads")
    print("Wrote:")
    print(f"  {os.path.join(OUT, 'dashboard.html')}   <- open this in your browser")
    print(f"  {os.path.join(OUT, 'summary.json')}        (high-level aggregates — this is what Framer fetches)")
    print(f"  {os.path.join(OUT, 'leads.json')}          (full detail, stays local — incl. customer names)")
    print(f"  {os.path.join(OUT, 'leads.csv')}")


# The dashboard + the Framer component share the same rendering logic. It lives
# in shared_dashboard.js so we keep ONE source of truth; the build inlines it.
def _shared_js():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_dashboard.js")
    with open(p) as fh:
        return fh.read()


DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Speed to Lead — Royalty Sports Performance</title>
<style>__CSS__</style>
</head><body>
<div id="stl-root"></div>
<script>window.__STL_DATA__ = /*__DATA__*/;</script>
<script>__JS__
  STL.mount(document.getElementById('stl-root'), window.__STL_DATA__);
</script>
</body></html>"""


if __name__ == "__main__":
    # Inline shared CSS/JS into the HTML template at build time.
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.css")
    with open(css_path) as fh:
        DASHBOARD_HTML = DASHBOARD_HTML.replace("__CSS__", fh.read())
    DASHBOARD_HTML = DASHBOARD_HTML.replace("__JS__", _shared_js())
    main()
