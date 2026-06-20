"""Core Speed-to-Lead computation.

Definition (locked with stakeholder):
  - Lead anchor      = contact dateAdded (net-new inbound lead arrival)
  - Stops the clock  = first MANUAL phone call or text message
                       (direction=outbound, source=app, messageType TYPE_SMS/TYPE_CALL).
                       Email and all automation are excluded.
  - Attribution      = userId on that first manual message (fallback: assignedTo)
  - Two clocks       = raw wall-clock AND business-hours-adjusted
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import mean, median

import business_hours as bh
from ghl_client import GHLClient, _to_ms

# Channels that are NOT real outbound communications (system/activity rows).
_ACTIVITY_PREFIX = "TYPE_ACTIVITY"

# Per stakeholder: speed-to-lead counts only manual phone calls and text messages
# (no email). Outbound + source=app guarantees a human sent it, not automation.
_RESPONSE_CHANNELS = {"TYPE_SMS", "TYPE_CALL"}

# Manual follow-up touches counted per rep (calls + texts + the rare manual email).
# Email never stops the speed-to-lead clock, but it counts as a follow-up touch.
_TOUCH_CHANNELS = {"TYPE_CALL": "call", "TYPE_SMS": "sms", "TYPE_EMAIL": "email"}


def is_manual_outbound(msg):
    """A human-sent outbound CALL or TEXT (the speed-to-lead clock-stopper)."""
    if msg.get("direction") != "outbound":
        return False
    if msg.get("source") != "app":
        return False
    return (msg.get("messageType") or "") in _RESPONSE_CHANNELS


def _analyze_contact(client, contact):
    """Single pass over a contact's messages. Returns:
      first   = (response_ms, userId, messageType) of the first manual call/text
                after the contact was created, or None
      touches = list of manual outbound touches {rep_id, ts, ch, dur, answered}
                (calls/texts/emails; dur+answered set for calls only)
      replied = True if the lead sent any inbound message after being created
    """
    anchor = _to_ms(contact.get("dateAdded"))
    first = None
    touches = []
    replied = False
    for conv in client.contact_conversations(contact["id"]):
        for m in client.conversation_messages(conv["id"]):
            mt = m.get("messageType") or ""
            if mt.startswith(_ACTIVITY_PREFIX) or mt == "TYPE_INTERNAL_COMMENT":
                continue
            mms = _to_ms(m.get("dateAdded"))
            if mms is None or mms < anchor:
                continue
            direction = m.get("direction")
            if direction == "inbound":
                replied = True
                continue
            # outbound from here
            if direction != "outbound" or m.get("source") != "app":
                continue
            if mt not in _TOUCH_CHANNELS:
                continue
            ch = _TOUCH_CHANNELS[mt]
            dur, answered = None, None
            if ch == "call":
                call = (m.get("meta") or {}).get("call") or {}
                dur = call.get("duration")
                answered = m.get("status") == "completed"
            touches.append({"rep_id": m.get("userId"), "ts": mms,
                            "ch": ch, "dur": dur, "answered": answered})
            # speed-to-lead clock stops at the first manual call or text (not email)
            if mt in _RESPONSE_CHANNELS and (first is None or mms < first[0]):
                first = (mms, m.get("userId"), mt)
    return first, touches, replied


def compute_leads(start_ms, end_ms, client=None, max_workers=8):
    """Return a list of per-lead result dicts for contacts created in the window."""
    client = client or GHLClient()
    contacts = list(client.search_contacts_between(start_ms, end_ms))

    def work(contact):
        anchor = _to_ms(contact.get("dateAdded"))
        first, touches, replied = _analyze_contact(client, contact)
        resp_ms, user_id, channel = first if first else (None, None, None)
        rep = user_id or contact.get("assignedTo")
        responded = resp_ms is not None
        return {
            "contactId": contact["id"],
            "name": (contact.get("contactName")
                     or contact.get("firstName")
                     or contact.get("email") or contact["id"]),
            "anchor_ms": anchor,
            "response_ms": resp_ms,
            "responded": responded,
            "rep_id": rep,
            "channel": channel,
            "raw_seconds": bh.raw_seconds(anchor, resp_ms) if responded else None,
            "bh_seconds": bh.business_seconds(anchor, resp_ms) if responded else None,
            "touches": touches,
            "replied": replied,
        }

    if not contacts:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(work, contacts))


def _summ(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"count": 0, "median": None, "avg": None, "min": None, "max": None}
    return {
        "count": len(vals),
        "median": median(vals),
        "avg": mean(vals),
        "min": min(vals),
        "max": max(vals),
    }


def aggregate(leads, user_names=None):
    """Roll per-lead results up into overall + per-rep + hour-of-day heatmap."""
    user_names = user_names or {}
    responded = [l for l in leads if l["responded"]]

    # Per-rep
    reps = {}
    for l in leads:
        rid = l["rep_id"] or "unassigned"
        reps.setdefault(rid, []).append(l)
    per_rep = []
    for rid, group in reps.items():
        g_resp = [l for l in group if l["responded"]]
        per_rep.append({
            "rep_id": rid,
            "rep_name": user_names.get(rid, "Unassigned" if rid == "unassigned" else rid),
            "leads": len(group),
            "responded": len(g_resp),
            "no_response": len(group) - len(g_resp),
            "raw": _summ([l["raw_seconds"] for l in g_resp]),
            "bh": _summ([l["bh_seconds"] for l in g_resp]),
        })
    per_rep.sort(key=lambda r: (r["bh"]["median"] is None, r["bh"]["median"] or 0))

    # Hour-of-day arrival heatmap (in business timezone)
    hod = {h: {"leads": 0, "bh_seconds": []} for h in range(24)}
    for l in leads:
        dt = datetime.fromtimestamp(l["anchor_ms"] / 1000.0, tz=timezone.utc).astimezone(bh._TZ)
        hod[dt.hour]["leads"] += 1
        if l["bh_seconds"] is not None:
            hod[dt.hour]["bh_seconds"].append(l["bh_seconds"])
    heatmap = []
    for h in range(24):
        bhs = hod[h]["bh_seconds"]
        heatmap.append({
            "hour": h,
            "leads": hod[h]["leads"],
            "median_bh_seconds": median(bhs) if bhs else None,
        })

    return {
        "totals": {
            "leads": len(leads),
            "responded": len(responded),
            "no_response": len(leads) - len(responded),
            "response_rate": (len(responded) / len(leads)) if leads else None,
            "raw": _summ([l["raw_seconds"] for l in responded]),
            "bh": _summ([l["bh_seconds"] for l in responded]),
        },
        "per_rep": per_rep,
        "heatmap": heatmap,
    }
