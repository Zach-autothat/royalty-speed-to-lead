"""Roll the per-lead dataset up into a small, high-level summary for the frontend.

The frontend never sees per-lead rows or raw timestamps — only these aggregates.
Output is a few KB: per window (7/14/30…) and per clock (business-hours / raw),
the headline numbers, per-rep table, response-time distribution, channel split,
and a day×hour arrival heatmap (counts only).
"""
import datetime
from statistics import mean as _mean, median as _median

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

DAY_MS = 86_400_000
BUCKETS = [("<5m", 0, 300), ("5–15m", 300, 900), ("15–30m", 900, 1800),
           ("30–60m", 1800, 3600), ("1–2h", 3600, 7200),
           ("2–4h", 7200, 14400), ("4h+", 14400, float("inf"))]
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _med(a):
    return _median(a) if a else None


def _avg(a):
    return _mean(a) if a else None


def _pctl(a, q):
    """Nearest-rank percentile (q in 0..1). Outlier-robust, unlike the mean."""
    if not a:
        return None
    b = sorted(a)
    return b[min(len(b) - 1, int(round(q * (len(b) - 1))))]


def _bucketize(times):
    return [sum(1 for x in times if lo <= x < hi) for _, lo, hi in BUCKETS]


def _clock_agg(leads, field):
    resp = [l for l in leads if l["responded"]]
    times = [l[field] for l in resp]
    reps = {}
    for l in leads:
        reps.setdefault(l["rep_name"], []).append(l)
    per_rep = []
    for rep, g in reps.items():
        gr = [l for l in g if l["responded"]]
        t = [l[field] for l in gr]
        per_rep.append({
            "rep": rep, "leads": len(g),
            "share": round(100 * len(g) / len(leads), 1) if leads else 0,
            "noResp": len(g) - len(gr),
            "avg": _avg(t), "median": _med(t), "p90": _pctl(t, 0.9),
            "dist": _bucketize(t),
        })
    per_rep.sort(key=lambda r: (r["rep"] == "Unassigned", r["avg"] is None, r["avg"] or 0))
    calls = sum(1 for l in resp if l["channel"] == "TYPE_CALL")
    texts = sum(1 for l in resp if l["channel"] == "TYPE_SMS")
    return {
        "total": len(leads), "responded": len(resp), "noResp": len(leads) - len(resp),
        "rate": round(100 * len(resp) / len(leads), 1) if leads else 0,
        "avg": _avg(times), "median": _med(times), "p90": _pctl(times, 0.9),
        "calls": calls, "texts": texts, "dist": _bucketize(times), "perRep": per_rep,
    }


def _heatmap(leads, tz):
    grid = [[0] * 24 for _ in range(7)]
    zone = ZoneInfo(tz) if ZoneInfo else None
    for l in leads:
        dt = datetime.datetime.fromtimestamp(l["anchor_ms"] / 1000, zone)
        grid[(dt.weekday() + 1) % 7][dt.hour] += 1  # Python Mon=0 -> Sun=0 index
    return grid


def _rep_activity(leads, names, tz):
    """Per-rep calling + follow-up detail for the rep drill-in view.
    Call/text activity is attributed to the rep who MADE each touch (touch.rep_id);
    lead-level metrics (reply rate, persistence) to the lead's owner (rep_name).
    """
    zone = ZoneInfo(tz) if ZoneInfo else None
    names = names or {}

    def rname(rid):
        return "Unassigned" if not rid else names.get(rid, rid)

    act, own = {}, {}

    def A(name):
        if name not in act:
            act[name] = {"dials": 0, "answered": 0, "over3": 0, "talkSec": 0,
                         "conn": 0, "texts": 0, "emails": 0,
                         "heatmap": [[0] * 24 for _ in range(7)]}
        return act[name]

    def O(name):
        if name not in own:
            own[name] = {"leadsOwned": 0, "replied": 0, "touchCounts": []}
        return own[name]

    for l in leads:
        o = O(l.get("rep_name") or "Unassigned")
        o["leadsOwned"] += 1
        if l.get("replied"):
            o["replied"] += 1
        o["touchCounts"].append(len(l.get("touches") or []))
        for t in (l.get("touches") or []):
            a = A(rname(t.get("rep_id")))
            ch = t.get("ch")
            if ch == "call":
                a["dials"] += 1
                if t.get("answered"):
                    a["conn"] += 1
                    dur = t.get("dur") or 0
                    a["talkSec"] += dur
                    if dur > 180:
                        a["over3"] += 1
                a["answered"] = a["conn"]
            elif ch == "sms":
                a["texts"] += 1
            elif ch == "email":
                a["emails"] += 1
            ts = t.get("ts")
            if ts is not None:
                dt = datetime.datetime.fromtimestamp(ts / 1000, zone)
                a["heatmap"][(dt.weekday() + 1) % 7][dt.hour] += 1

    out = {}
    for name in (set(act) | set(own)) - {"Unassigned"}:
        a = act.get(name) or {
            "dials": 0, "answered": 0, "over3": 0, "talkSec": 0, "conn": 0,
            "texts": 0, "emails": 0, "heatmap": [[0] * 24 for _ in range(7)]}
        o = own.get(name, {"leadsOwned": 0, "replied": 0, "touchCounts": []})
        dials, conn = a["dials"], a["conn"]
        dist = [0, 0, 0, 0]
        for c in o["touchCounts"]:
            if c >= 1:
                dist[min(c, 4) - 1] += 1
        total_touches = sum(o["touchCounts"])
        owned = o["leadsOwned"]
        out[name] = {
            "dials": dials, "answered": a["answered"],
            "answerRate": round(100 * a["answered"] / dials, 1) if dials else 0,
            "over3": a["over3"],
            "over3Rate": round(100 * a["over3"] / dials, 1) if dials else 0,
            "talkSec": a["talkSec"],
            "avgCallSec": round(a["talkSec"] / conn) if conn else 0,
            "texts": a["texts"], "emails": a["emails"],
            "totalTouches": total_touches,
            "avgTouchesPerLead": round(total_touches / owned, 1) if owned else 0,
            "touchDist": dist,
            "leadsOwned": owned, "replied": o["replied"],
            "replyRate": round(100 * o["replied"] / owned, 1) if owned else 0,
            "heatmap": a["heatmap"],
        }
    return out


def build_summary(leads, meta, names=None):
    tz = meta["business_hours"]["tz"]
    now = meta["generated_ms"]
    wd = meta.get("window_days") or 30
    windows = [d for d in (7, 14, 30, 90) if d <= wd] or [wd]

    data = {}
    win_meta = []
    for d in windows:
        sub = [l for l in leads if l["anchor_ms"] >= now - d * DAY_MS]
        key = f"{d}d"
        win_meta.append({"key": key, "label": f"{d} days", "days": d})
        data[key] = {
            "heatmap": _heatmap(sub, tz),
            "bh": _clock_agg(sub, "bh_seconds"),
            "raw": _clock_agg(sub, "raw_seconds"),
            "repActivity": _rep_activity(sub, names, tz),
        }
    return {
        "meta": meta,
        "buckets": [b[0] for b in BUCKETS],
        "days": DAYS,
        "windows": win_meta,
        "data": data,
    }
