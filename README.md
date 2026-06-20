# Royalty GHL — Speed to Lead

Tool #1 in the GHL toolkit. Measures how fast reps make **manual** first contact
with net-new inbound leads, with raw and business-hours-adjusted clocks.

## What it measures

| | |
|---|---|
| **Lead** | A contact, anchored at `dateAdded` (when it entered GHL) |
| **Clock stops at** | The first **manual phone call or text** (`source = app`, `messageType` `TYPE_SMS`/`TYPE_CALL`). **Email and all automation are excluded** |
| **Headline metrics** | **Average** response (most-watched) + **median** (typical) shown side by side, **lead-share %** per rep, and a response-time distribution |
| **Attribution** | The rep (`userId`) who sent that first manual message |
| **Two clocks** | Raw wall-clock + business-hours-adjusted (Mon–Sun 8am–6pm US/Central) |

## Per-rep drill-in

Click a rep in the dashboard to open their personal page. Metrics cover the
**cohort of leads that rep received in the selected window** (7/14/30d) and every
manual call/text/email to them. Call activity is attributed to the rep who *made*
each call (`message.userId`); reply/persistence to the lead's owner.

| Metric | Definition |
|---|---|
| **Answer rate** | Calls with `status == completed` ÷ total dials |
| **Calls > 3 min** | Calls with `meta.call.duration > 180` ÷ total dials (real conversations) |
| **Talk time / avg length** | Sum of connected-call durations; avg over connected calls |
| **Follow-ups by channel** | Manual calls / texts / emails sent |
| **Persistence** | Avg touches per lead + distribution (leads with 1 / 2 / 3 / 4+ touches) |
| **Reply rate** | Leads (owned by rep) with any inbound reply ÷ leads owned |
| **Activity heatmap** | Day × hour of the rep's own outbound calls/texts |

Computed in `speed_to_lead.py` (`_analyze_contact` collects per-lead `touches` +
`replied`) and aggregated in `summarize.py` (`_rep_activity` → `data[win].repActivity`).
Manual email is rare (mostly automation), so email counts are usually small.

## Architecture (why it's built this way)

```
GHL API ─▶ refresh.py ─▶ out/summary.json ─▶ build_worker.py ─▶ Cloudflare Worker
          (heavy compute,   (few KB of          (bakes summary      (serves it with
           token here)       aggregates,         into a Worker)      CORS)
                             no PII)                                     │
                                                                        ▼
                                                          Framer SpeedToLead.tsx
                                                          (NO data in the code —
                                                           fetches summary on load)
```

The token **never** reaches the browser, and **no data lives in the Framer code**.
The browser fetches only a few KB of high-level aggregates (no per-lead rows, no
timestamps, no PII). Heavy GHL work happens once, server-side, in `refresh.py`.

## Files

| File | Role |
|---|---|
| `config.py` | Loads `.env` (token, location, business hours) |
| `ghl_client.py` | **Foundation** — GHL v2 client (auth, pagination, retry). Every future tool reuses this |
| `business_hours.py` | Business-hours-adjusted duration math |
| `speed_to_lead.py` | Core computation (lead → first manual call/text → per-rep) |
| `summarize.py` | Rolls per-lead data up into the small `summary.json` the frontend fetches |
| `validate.py` | Prints the report to the terminal — spot-check numbers |
| `refresh.py` | Pulls GHL once, writes `out/` (summary.json, dashboard.html, leads.json, csv) |
| `build_worker.py` | Bakes `summary.json` into `worker/speed-to-lead-data.js` |
| `worker/speed-to-lead-data.js` | Cloudflare Worker that serves the summary with CORS |
| `framer/SpeedToLead.tsx` | Framer code component — pure fetch + render, contains no data |

## Run it

```bash
cd "Royalty GHL"
python3 validate.py 7d        # quick terminal check (7d / 14d / 30d / all)
python3 refresh.py 30d        # pull GHL → out/summary.json + dashboard.html + leads.json
python3 build_worker.py       # bake summary into worker/speed-to-lead-data.js
open out/dashboard.html       # local interactive dashboard, no deploy needed
```

`refresh.py` windows: `7d`, `30d`, `90d`, `all`. Larger windows = more GHL calls and
longer runtime (30d ≈ 2 min / ~600 leads; `all` is several minutes — run sparingly).

## Deploy to Framer

1. **Deploy the Worker.** Cloudflare → Workers & Pages → Create → Worker → paste the
   contents of `worker/speed-to-lead-data.js` (~5 KB) → Deploy. Copy its URL.
2. **Paste the component.** Framer → Assets ▸ Code ▸ New Code File → paste
   `framer/SpeedToLead.tsx`.
3. **Connect them.** Drag the component on the canvas, set its **Data URL** property
   to the Worker URL. It fetches fresh on every page load.

## Keeping it fresh

The Worker serves whatever was last baked. To update the numbers, re-run the three
commands (`refresh.py` → `build_worker.py` → redeploy) on a schedule (cron/launchd/
GitHub Action). Cleaner long-term: store `summary.json` in Cloudflare KV and have the
Worker read it, so refreshes need no redeploy — ask when you want that wired up.

## Keeping it fresh

`refresh.py` is a one-shot. To keep the hosted JSON current, run it on a schedule
(macOS `launchd`/cron, a GitHub Action, or any box with Python) and re-upload
`leads.public.json`. No serverless timeout concerns because the heavy GHL work
happens in the scheduled job, not on page load.

## Notes / gotchas

- **Token** lives only in `.env` (git-ignored). Rotate anytime in GHL → Settings →
  Private Integrations.
- **After-hours leads** answered after 6pm show `0s` business-hours time by
  definition (the clock doesn't run after close). Raw time still captures it.
- **Cloudflare** in front of the API blocks the default urllib User-Agent; the
  client sends a browser-like UA to get through.
