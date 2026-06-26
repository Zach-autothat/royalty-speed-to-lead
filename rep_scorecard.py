"""Rep Performance Scorecard (Tool #3) — data feed for the Google-Sheet dashboard.

Rolls two existing sources up per rep, per grain (week / month / year), per period:
  - Speed-to-Lead   : leads, speed-to-first-contact, no-contact rate, dials,
                      answer rate, texts, touches/lead  (from this repo)
  - Call Intelligence: calls scored, avg score, qualification /7, next-step rate
                      (from the gated Worker's calls.json)

It POSTs ONE flat table (rep × grain × period × metrics) to a sheet-bound Apps
Script web app. The script renders the readable pages: a per-rep tab showing the
selected period vs the previous period (this / last / change) against editable
targets, a Compare-all tab, and trend sparklines. Switching the in-sheet
Week/Month/Year dropdown re-renders instantly from this same data — no re-run.

Run:
  python3 rep_scorecard.py                       # all-time leads + calls -> push
  python3 rep_scorecard.py --preview              # write out/rep_scorecard_data.json, no push
  python3 rep_scorecard.py --leads out/leads.json # use an existing leads file
"""
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

TZ = ZoneInfo("America/Chicago") if ZoneInfo else None
EXCLUDE_REPS = {"Unassigned"}

# Metric columns, in display order. The Apps Script knows these keys + their
# meaning (target, direction, formatting); keep the two in sync if you add one.
METRIC_KEYS = ["leads", "median_stl_min", "nocontact_pct", "dials", "answer_pct",
               "texts", "touches_per_lead", "calls_scored", "avg_score",
               "qual_avg", "nextstep_pct"]


def _dt(ms):
    return datetime.fromtimestamp(ms / 1000, TZ)


def wk_key(ms):
    y, w, _ = _dt(ms).isocalendar()
    return f"{y}-W{w:02d}"


def mo_key(ms):
    d = _dt(ms)
    return f"{d.year}-{d.month:02d}"


def yr_key(ms):
    return str(_dt(ms).year)


GRAINS = [("Week", wk_key), ("Month", mo_key), ("Year", yr_key)]


# ---- rollup --------------------------------------------------------------
def _blank():
    return {"leads": 0, "nocontact": 0, "stl": [], "dials": 0, "answered": 0,
            "texts": 0, "emails": 0, "calls": 0, "score": [], "qual": [], "nextstep": 0}


def rollup(leads, calls, period_fn):
    P = {}

    def cell(rep, per):
        return P.setdefault((rep, per), _blank())

    for l in leads:
        rep = l.get("rep_name")
        if not rep or rep in EXCLUDE_REPS:
            continue
        c = cell(rep, period_fn(l["anchor_ms"]))
        c["leads"] += 1
        if l.get("responded"):
            if l.get("bh_seconds") is not None:
                c["stl"].append(l["bh_seconds"])
        else:
            c["nocontact"] += 1
        for t in (l.get("touches") or []):
            ts, ch = t.get("ts"), t.get("ch")
            if ts is None:
                continue
            c2 = cell(rep, period_fn(ts))
            if ch == "call":
                c2["dials"] += 1
                if t.get("answered"):
                    c2["answered"] += 1
            elif ch == "sms":
                c2["texts"] += 1
            elif ch == "email":
                c2["emails"] += 1

    for x in calls:
        rep = x.get("repName")
        if not rep or rep in EXCLUDE_REPS:
            continue
        c = cell(rep, period_fn(x["ts"]))
        c["calls"] += 1
        c["score"].append(x["score"])
        if x.get("callType") == "intro":
            c["qual"].append(x["qualScore"])
        if x.get("nextStep", "none") != "none":
            c["nextstep"] += 1
    return P


def _r(x, n=0):
    return None if x is None else (round(x, n) if n else round(x))


def finalize(raw):
    leads = raw["leads"]
    touches = raw["dials"] + raw["texts"] + raw["emails"]
    return {
        "leads": leads,
        "median_stl_min": _r(statistics.median(raw["stl"]) / 60) if raw["stl"] else None,
        "nocontact_pct": _r(100 * raw["nocontact"] / leads) if leads else None,
        "dials": raw["dials"],
        "answer_pct": _r(100 * raw["answered"] / raw["dials"]) if raw["dials"] else None,
        "texts": raw["texts"],
        "touches_per_lead": _r(touches / leads, 1) if leads else None,
        "calls_scored": raw["calls"],
        "avg_score": _r(statistics.mean(raw["score"])) if raw["score"] else None,
        "qual_avg": _r(statistics.mean(raw["qual"]), 1) if raw["qual"] else None,
        "nextstep_pct": _r(100 * raw["nextstep"] / raw["calls"]) if raw["calls"] else None,
    }


def build_data_rows(leads, calls):
    """Flat table: [Rep, Grain, Period, <metric values...>] over all grains/periods."""
    rows, reps = [], set()
    for grain, fn in GRAINS:
        for (rep, per), raw in rollup(leads, calls, fn).items():
            reps.add(rep)
            m = finalize(raw)
            rows.append([rep, grain, per] + [("" if m[k] is None else m[k]) for k in METRIC_KEYS])
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return rows, sorted(reps)


# ---- inputs --------------------------------------------------------------
def load_calls():
    url = os.environ.get("CALL_DATA_URL", "https://royalty-call-intel.zach-a82.workers.dev")
    key = os.environ.get("CALL_ACCESS_KEY", "")
    local = os.environ.get("CALL_DATA_FILE")
    if local and os.path.exists(local):
        return json.load(open(local)).get("calls", [])
    req = urllib.request.Request(f"{url.rstrip('/')}/?k={key}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode()).get("calls", [])


def load_leads(leads_file=None):
    if leads_file:
        return json.load(open(leads_file)).get("leads", [])
    import time
    import speed_to_lead as stl
    from ghl_client import GHLClient
    client = GHLClient()
    leads = stl.compute_leads(0, int(time.time() * 1000), client=client)
    names = client.users()
    for l in leads:
        l["rep_name"] = names.get(l["rep_id"], "Unassigned" if not l["rep_id"] else l["rep_id"])
    return leads


# ---- push ----------------------------------------------------------------
def push(reps, rows):
    url = os.environ["SCORECARD_WEBAPP_URL"]
    token = os.environ.get("SCORECARD_TOKEN", "")
    payload = {"token": token, "action": "sync", "reps": reps,
               "metricKeys": METRIC_KEYS, "data": rows}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        txt = r.read().decode()
    try:
        print("Pushed. Response:", json.loads(txt))
    except ValueError:
        print("Pushed. Raw response:", txt[:300])


def main():
    args = sys.argv[1:]
    preview = "--preview" in args
    leads_file = args[args.index("--leads") + 1] if "--leads" in args else None

    leads = load_leads(leads_file)
    calls = load_calls()
    print(f"Loaded {len(leads)} leads, {len(calls)} scored calls.", flush=True)

    rows, reps = build_data_rows(leads, calls)
    print(f"Built {len(rows)} rep×grain×period rows for {len(reps)} reps: {', '.join(reps)}", flush=True)

    if preview:
        os.makedirs("out", exist_ok=True)
        with open("out/rep_scorecard_data.json", "w") as fh:
            json.dump({"reps": reps, "metricKeys": METRIC_KEYS, "data": rows}, fh, indent=2)
        print("Wrote out/rep_scorecard_data.json (preview — no push).")
        return
    push(reps, rows)


if __name__ == "__main__":
    main()
