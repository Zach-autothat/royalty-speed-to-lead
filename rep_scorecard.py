"""Rep Performance Scorecard (Tool #3) — per-rep weekly / monthly / yearly rollup.

Pulls two existing data sources and rolls them up per rep, per period, then pushes
the result into a Google Sheet (auto-updating, private):
  - Speed-to-Lead  : lead activity + responsiveness (leads, speed-to-first-contact,
                     no-contact rate, dials, answer rate, texts, touches/lead).
                     Source = this repo (speed_to_lead.compute_leads / out/leads.json).
  - Call Intelligence: call quality (calls scored, avg score, qualification /7,
                     next-step rate). Source = the gated Worker's calls.json.

Answers one question per rep: are they doing what they're supposed to? Each metric is
compared to an editable Target; a 🟢/🟡/🔴 status falls out of that.

Tabs written to the sheet:
  Scorecard  - current period, all reps, headline metrics + status (computed each run)
  Weekly / Monthly / Yearly - every rep × period, all metrics (the history)
  Targets    - editable Metric | Target | Notes; SEEDED once, then only READ (never
               overwritten) so the team's thresholds + notes persist.

Run:
  python3 rep_scorecard.py                 # compute (all-time leads) + push to Sheets
  python3 rep_scorecard.py --preview        # compute + write out/rep_scorecard.json, NO push
  python3 rep_scorecard.py --leads out/leads.json   # use an existing leads file instead of GHL
"""
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME) if ZoneInfo else None

# Reps to track (Unassigned and unknown ids are dropped). Auto-discovered from data,
# but anyone with no activity in a period simply doesn't get a row that period.
EXCLUDE_REPS = {"Unassigned"}

# Seeded default targets (editable in the sheet's Targets tab afterwards).
#   dir "lo" = lower is better (breach when actual > target); "hi" = higher is better.
TARGETS = [
    {"key": "median_stl_min", "label": "Median speed-to-lead (min)", "target": 15, "dir": "lo",
     "notes": "First manual call/text. Faster is better."},
    {"key": "nocontact_pct", "label": "No-contact leads (%)", "target": 5, "dir": "lo",
     "notes": "Leads never called or texted. Should be near zero."},
    {"key": "answer_pct", "label": "Answer rate (%)", "target": 70, "dir": "hi",
     "notes": "Dials that connected."},
    {"key": "avg_score", "label": "Avg call score", "target": 70, "dir": "hi",
     "notes": "Call Intel score vs the playbook (0-100)."},
    {"key": "qual_avg", "label": "Qualification /7", "target": 5, "dir": "hi",
     "notes": "Tier-1 questions asked on intro calls."},
    {"key": "nextstep_pct", "label": "Next-step booked (%)", "target": 40, "dir": "hi",
     "notes": "Calls that ended with a booked next step."},
]
# Metrics that drive the status light (the "are they doing their job" core).
STATUS_KEYS = ["median_stl_min", "nocontact_pct", "avg_score", "qual_avg"]
LOW_VOLUME_LEADS = 8     # below this many leads AND...
LOW_VOLUME_CALLS = 3     # ...this many scored calls -> "Low volume" (don't judge yet)

# Column order for the Weekly/Monthly/Yearly history tabs.
COLUMNS = [
    ("rep", "Rep"), ("period", "Period"), ("leads", "Leads"),
    ("nocontact_pct", "No-contact %"), ("median_stl_min", "Median speed (min)"),
    ("dials", "Dials"), ("answer_pct", "Answer %"), ("texts", "Texts"),
    ("touches_per_lead", "Touches/lead"), ("calls_scored", "Calls scored"),
    ("avg_score", "Avg score"), ("qual_avg", "Qual /7"),
    ("nextstep_pct", "Next-step %"), ("status", "Status"),
]
SCORECARD_COLUMNS = [
    ("rep", "Rep"), ("leads", "Leads"), ("median_stl_min", "Speed (min)"),
    ("nocontact_pct", "No-contact %"), ("dials", "Dials"),
    ("avg_score", "Avg score"), ("qual_avg", "Qual /7"), ("status", "Status"),
]


# ---- period bucketing ----------------------------------------------------
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


# ---- rollup --------------------------------------------------------------
def _blank():
    return {"leads": 0, "nocontact": 0, "stl": [], "dials": 0, "answered": 0,
            "texts": 0, "emails": 0, "calls": 0, "score": [], "qual": [], "nextstep": 0}


def rollup(leads, calls, period_fn):
    """Return {(rep, period): raw_metrics}."""
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


def _round(x, n=0):
    return None if x is None else (round(x, n) if n else round(x))


def finalize(raw):
    """Turn one raw cell into the displayed metric values (or None when N/A)."""
    leads = raw["leads"]
    touches = raw["dials"] + raw["texts"] + raw["emails"]
    m = {
        "leads": leads,
        "nocontact_pct": _round(100 * raw["nocontact"] / leads) if leads else None,
        "median_stl_min": _round(statistics.median(raw["stl"]) / 60) if raw["stl"] else None,
        "dials": raw["dials"],
        "answer_pct": _round(100 * raw["answered"] / raw["dials"]) if raw["dials"] else None,
        "texts": raw["texts"],
        "touches_per_lead": _round(touches / leads, 1) if leads else None,
        "calls_scored": raw["calls"],
        "avg_score": _round(statistics.mean(raw["score"])) if raw["score"] else None,
        "qual_avg": _round(statistics.mean(raw["qual"]), 1) if raw["qual"] else None,
        "nextstep_pct": _round(100 * raw["nextstep"] / raw["calls"]) if raw["calls"] else None,
    }
    return m


def status_for(m, targets):
    if (m["leads"] or 0) < LOW_VOLUME_LEADS and (m["calls_scored"] or 0) < LOW_VOLUME_CALLS:
        return "Low volume"
    tmap = {t["key"]: t for t in targets}
    breaches = 0
    for k in STATUS_KEYS:
        v = m.get(k)
        if v is None:
            continue
        t = tmap.get(k)
        if not t:
            continue
        if t["dir"] == "lo" and v > t["target"]:
            breaches += 1
        elif t["dir"] == "hi" and v < t["target"]:
            breaches += 1
    return "On track" if breaches == 0 else ("Watch" if breaches == 1 else "Off track")


def build_table(leads, calls, period_fn, targets, sort_periods_desc=True):
    P = rollup(leads, calls, period_fn)
    rows = []
    for (rep, per), raw in P.items():
        m = finalize(raw)
        m["rep"], m["period"] = rep, per
        m["status"] = status_for(m, targets)
        rows.append(m)
    rows.sort(key=lambda r: (r["period"], r["rep"]), reverse=False)
    if sort_periods_desc:
        rows.sort(key=lambda r: r["period"], reverse=True)
    return rows


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
    # Compute fresh over all history so monthly/yearly rollups have depth.
    import time
    import speed_to_lead as stl
    from ghl_client import GHLClient
    client = GHLClient()
    leads = stl.compute_leads(0, int(time.time() * 1000), client=client)
    names = client.users()
    for l in leads:
        l["rep_name"] = names.get(l["rep_id"], "Unassigned" if not l["rep_id"] else l["rep_id"])
    return leads


# ---- Google Sheets push --------------------------------------------------
def push_to_sheets(weekly, monthly, yearly, targets):
    import gspread  # imported lazily so --preview needs no deps
    from google.oauth2.service_account import Credentials

    sheet_id = os.environ["GSHEET_ID"]
    sa_json = os.environ.get("GOOGLE_SA_JSON")
    info = json.loads(sa_json) if sa_json else json.load(
        open(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]))
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    existing = {ws.title for ws in sh.worksheets()}

    def ensure(title, rows, cols):
        if title in existing:
            return sh.worksheet(title)
        return sh.add_worksheet(title=title, rows=rows, cols=cols)

    # Targets: seed ONCE, then never touch (team edits persist; we re-read them).
    if "Targets" not in existing:
        ws = ensure("Targets", 30, 4)
        ws.update([["Metric", "Target", "Direction", "Notes"]] +
                  [[t["label"], t["target"], "lower is better" if t["dir"] == "lo"
                    else "higher is better", t["notes"]] for t in targets],
                  value_input_option="USER_ENTERED")
    targets = read_targets(sh, targets)

    # History tabs: full overwrite each run (pure data).
    for title, rows in (("Weekly", weekly), ("Monthly", monthly), ("Yearly", yearly)):
        ws = ensure(title, max(50, len(rows) + 5), len(COLUMNS))
        header = [lbl for _, lbl in COLUMNS]
        body = [[fmt(r.get(k)) for k, _ in COLUMNS] for r in rows]
        ws.clear()
        ws.update([header] + body, value_input_option="USER_ENTERED")

    # Scorecard: latest period per grain (we show the latest MONTH by default).
    latest = latest_period_rows(monthly)
    ws = ensure("Scorecard", 60, len(SCORECARD_COLUMNS))
    header = [lbl for _, lbl in SCORECARD_COLUMNS]
    body = [[fmt(r.get(k)) for k, _ in SCORECARD_COLUMNS] for r in latest]
    ws.clear()
    ws.update([header] + body, value_input_option="USER_ENTERED")
    _apply_status_colors(sh, ws.id, len(body), SCORECARD_COLUMNS)
    print(f"Pushed: Weekly {len(weekly)}, Monthly {len(monthly)}, Yearly {len(yearly)} rows; "
          f"Scorecard {len(latest)} reps (latest month).")


def read_targets(sh, defaults):
    try:
        rows = sh.worksheet("Targets").get_all_values()[1:]
    except Exception:
        return defaults
    by_label = {t["label"]: dict(t) for t in defaults}
    for r in rows:
        if len(r) >= 2 and r[0] in by_label:
            try:
                by_label[r[0]]["target"] = float(r[1])
            except (ValueError, TypeError):
                pass
    return list(by_label.values())


def latest_period_rows(rows):
    if not rows:
        return []
    latest = max(r["period"] for r in rows)
    return sorted([r for r in rows if r["period"] == latest], key=lambda r: r["rep"])


def fmt(v):
    return "—" if v is None else v


def _apply_status_colors(sh, ws_id, n_rows, columns):
    """Conditional-format the Status column by text. Set once; survives data writes."""
    col = [k for k, _ in columns].index("status")
    rng = {"sheetId": ws_id, "startRowIndex": 1, "endRowIndex": n_rows + 1,
           "startColumnIndex": col, "endColumnIndex": col + 1}
    palette = [("On track", 0.82, 0.92, 0.79), ("Watch", 0.98, 0.91, 0.71),
               ("Off track", 0.96, 0.80, 0.80), ("Low volume", 0.90, 0.90, 0.88)]
    reqs = []
    for text, r, g, b in palette:
        reqs.append({"addConditionalFormatRule": {"rule": {"ranges": [rng], "booleanRule": {
            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": text}]},
            "format": {"backgroundColor": {"red": r, "green": g, "blue": b}}}}, "index": 0}})
    try:
        sh.batch_update({"requests": reqs})
    except Exception as e:
        print(f"(status colors skipped: {e})")


# ---- main ----------------------------------------------------------------
def main():
    args = sys.argv[1:]
    preview = "--preview" in args
    leads_file = None
    if "--leads" in args:
        leads_file = args[args.index("--leads") + 1]

    leads = load_leads(leads_file)
    calls = load_calls()
    print(f"Loaded {len(leads)} leads, {len(calls)} scored calls.", flush=True)

    weekly = build_table(leads, calls, wk_key, TARGETS)
    monthly = build_table(leads, calls, mo_key, TARGETS)
    yearly = build_table(leads, calls, yr_key, TARGETS)

    if preview:
        out = {"weekly": weekly, "monthly": monthly, "yearly": yearly, "targets": TARGETS}
        os.makedirs("out", exist_ok=True)
        with open("out/rep_scorecard.json", "w") as fh:
            json.dump(out, fh, indent=2)
        print("Wrote out/rep_scorecard.json (preview — no push).")
        return
    push_to_sheets(weekly, monthly, yearly, TARGETS)


if __name__ == "__main__":
    main()
