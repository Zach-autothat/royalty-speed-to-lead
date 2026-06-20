"""Business-hours-adjusted elapsed time.

Given two UTC instants (epoch ms), returns the number of seconds that fall
inside the configured business window, in the configured timezone. A lead that
arrives at 11pm doesn't accrue wait time until the next open.
"""
from datetime import datetime, timedelta, timezone

import config

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(config.BH_TIMEZONE)
except Exception:  # pragma: no cover - fallback if tz database unavailable
    _TZ = timezone(timedelta(hours=-5))  # US Central (CDT) approximation


def _parse_hm(s):
    h, m = s.split(":")
    return int(h), int(m)


_OPEN_H, _OPEN_M = _parse_hm(config.BH_OPEN)
_CLOSE_H, _CLOSE_M = _parse_hm(config.BH_CLOSE)
_WORKDAYS = set(config.BH_WORKDAYS)  # 0=Mon .. 6=Sun


def _dt(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def business_seconds(start_ms, end_ms):
    """Seconds between start and end that fall within business hours."""
    if end_ms <= start_ms:
        return 0.0
    start = _dt(start_ms).astimezone(_TZ)
    end = _dt(end_ms).astimezone(_TZ)

    total = 0.0
    day = start.date()
    last = end.date()
    while day <= last:
        if day.weekday() in _WORKDAYS:
            win_open = datetime(day.year, day.month, day.day, _OPEN_H, _OPEN_M, tzinfo=_TZ)
            win_close = datetime(day.year, day.month, day.day, _CLOSE_H, _CLOSE_M, tzinfo=_TZ)
            lo = max(start, win_open)
            hi = min(end, win_close)
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += timedelta(days=1)
    return total


def raw_seconds(start_ms, end_ms):
    return max(0.0, (end_ms - start_ms) / 1000.0)


def fmt_duration(seconds):
    """Human-readable like '2h 14m' or '3m 5s'."""
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"
