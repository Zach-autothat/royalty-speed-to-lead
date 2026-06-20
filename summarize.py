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
            "avg": _avg(t), "median": _med(t),
        })
    per_rep.sort(key=lambda r: (r["rep"] == "Unassigned", r["avg"] is None, r["avg"] or 0))
    dist = [sum(1 for x in times if lo <= x < hi) for _, lo, hi in BUCKETS]
    calls = sum(1 for l in resp if l["channel"] == "TYPE_CALL")
    texts = sum(1 for l in resp if l["channel"] == "TYPE_SMS")
    return {
        "total": len(leads), "responded": len(resp), "noResp": len(leads) - len(resp),
        "rate": round(100 * len(resp) / len(leads), 1) if leads else 0,
        "avg": _avg(times), "median": _med(times),
        "calls": calls, "texts": texts, "dist": dist, "perRep": per_rep,
    }


def _heatmap(leads, tz):
    grid = [[0] * 24 for _ in range(7)]
    zone = ZoneInfo(tz) if ZoneInfo else None
    for l in leads:
        dt = datetime.datetime.fromtimestamp(l["anchor_ms"] / 1000, zone)
        grid[(dt.weekday() + 1) % 7][dt.hour] += 1  # Python Mon=0 -> Sun=0 index
    return grid


def build_summary(leads, meta):
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
        }
    return {
        "meta": meta,
        "buckets": [b[0] for b in BUCKETS],
        "days": DAYS,
        "windows": win_meta,
        "data": data,
    }
