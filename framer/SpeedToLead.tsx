// Speed to Lead — Framer Code Component (Royalty Team Gear design language)
// ---------------------------------------------------------------------------
// Contains NO data. On every page load it fetches a small, high-level summary
// (a few KB of aggregates — no per-lead rows, no PII) from the Data URL and
// renders it. Point Data URL at the Cloudflare Worker (worker/speed-to-lead-data.js).
//
// Metric: first MANUAL phone call or text to a net-new inbound lead (email and
// automation excluded). Two clocks: raw and business-hours (Mon–Sun 8a–6p CT).
import { useState, useEffect } from "react"
import { addPropertyControls, ControlType } from "framer"

const C = {
    bg: "#f7f6f3", surface: "#ffffff", border: "#e8e6e1",
    text: "#111110", muted: "#6b6b67", faint: "#9b9b97",
    accent: "#e8612c", accentBg: "#fdf1ec",
    green: "#1a7a4a", greenBg: "#edf7f2", amber: "#9a6b00",
    red: "#c0392b", redBg: "#fdf0ef", blue: "#1a5fa8", blueBg: "#eef4fd",
}
const REP_COLORS = ["#e8612c", "#1a5fa8", "#1a7a4a", "#9a6b00", "#6b3fa0", "#c0392b"]
const BUCKET_COLORS = [C.green, C.green, C.amber, C.amber, C.amber, C.red, C.red]

const pct = (a: number, b: number) => (b > 0 ? (a / b) * 100 : 0)
const fmtPct = (n: number) => `${Number(n).toFixed(1)}%`
const fmtNum = (n: number) => Math.round(n).toLocaleString()
function fmtDur(s: number | null) {
    if (s === null || s === undefined) return "—"
    s = Math.round(s)
    if (s < 60) return `${s}s`
    let m = Math.floor(s / 60), r = s % 60
    if (m < 60) return r ? `${m}m ${r}s` : `${m}m`
    let h = Math.floor(m / 60); m = m % 60
    if (h < 24) return `${h}h ${m}m`
    const d = Math.floor(h / 24); h = h % 24
    return `${d}d ${h}h`
}

const Card = ({ children, style }: any) => (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "18px 20px", ...style }}>{children}</div>
)
const Label = ({ children, right }: any) => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.09em" }}>{children}</span>
        {right}
    </div>
)
const Chip = ({ on, onClick, children }: any) => (
    <button onClick={onClick} style={{ padding: "5px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? C.accent : C.border}`, background: on ? C.accentBg : "transparent", color: on ? C.accent : C.muted }}>{children}</button>
)
function Tile({ label, value, sub, color, bg }: any) {
    return (
        <div style={{ background: bg || C.surface, border: `1px solid ${bg ? color + "44" : C.border}`, borderRadius: 12, padding: "16px 18px" }}>
            <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 9 }}>{label}</div>
            <div style={{ fontSize: 26, fontFamily: "'Sora', sans-serif", fontWeight: 800, color: color || C.text, lineHeight: 1 }}>{value}</div>
            {sub && <div style={{ fontSize: 12, color: C.faint, marginTop: 6 }}>{sub}</div>}
        </div>
    )
}

export default function SpeedToLead(props: { dataUrl: string }) {
    const { dataUrl } = props
    const [s, setS] = useState<any>(null)
    const [err, setErr] = useState<string | null>(null)
    const [win, setWin] = useState<string | null>(null)
    const [clock, setClock] = useState<"bh" | "raw">("bh")

    useEffect(() => {
        if (!dataUrl || dataUrl.indexOf("YOUR-HOST") >= 0) return
        setErr(null)
        fetch(dataUrl, { cache: "no-store" })
            .then((r) => (r.ok ? r.json() : Promise.reject("HTTP " + r.status)))
            .then((d) => { setS(d); setWin(d.windows[d.windows.length - 1].key) })
            .catch((e) => setErr(String(e)))
    }, [dataUrl])

    const wrap = { background: C.bg, fontFamily: "'DM Sans', sans-serif", color: C.text, padding: 24, borderRadius: 14 } as const
    const font = <link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&display=swap" rel="stylesheet" />

    if (!dataUrl || dataUrl.indexOf("YOUR-HOST") >= 0)
        return <div style={wrap}>{font}<div style={{ color: C.muted, fontSize: 13 }}>Set the <b>Data URL</b> property (right-hand panel) to load the dashboard.</div></div>
    if (err) return <div style={wrap}>{font}<div style={{ color: C.red, fontSize: 13 }}>Couldn’t load data: {err}</div></div>
    if (!s || !win) return <div style={wrap}>{font}<div style={{ color: C.faint, fontSize: 13 }}>Loading…</div></div>

    const a = s.data[win][clock]
    const heat = s.data[win].heatmap
    const bh = s.meta.business_hours
    const tz = bh.tz
    const HOURS = Array.from({ length: 24 }, (_, i) => i)
    const heatMax = Math.max(1, ...heat.flat())
    const heatColor = (v: number) => { if (!v) return C.bg; const t = v / heatMax; return t < 0.25 ? "#fde8df" : t < 0.5 ? "#f8b99a" : t < 0.75 ? "#f08055" : C.accent }
    const fmtH = (h: number) => (h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`)
    const distTot = a.dist.reduce((x: number, y: number) => x + y, 0)
    const distPeak = Math.max(1, ...a.dist)

    let repIdx = -1

    return (
        <div style={wrap}>
            {font}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
                <div>
                    <div style={{ fontSize: 22, fontFamily: "'Sora', sans-serif", fontWeight: 800 }}>Speed to Lead</div>
                    <div style={{ fontSize: 12, color: C.faint, marginTop: 2 }}>{s.meta.location} · manual calls + texts only · {bh.open}–{bh.close} {tz}</div>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {s.windows.map((w: any) => <Chip key={w.key} on={win === w.key} onClick={() => setWin(w.key)}>{w.label}</Chip>)}
                    <span style={{ width: 1, height: 22, background: C.border, margin: "0 2px" }} />
                    <Chip on={clock === "bh"} onClick={() => setClock("bh")}>Business hrs</Chip>
                    <Chip on={clock === "raw"} onClick={() => setClock("raw")}>Raw</Chip>
                </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 16 }}>
                <Tile label="Avg response" value={fmtDur(a.avg)} sub="most-watched" color={C.accent} bg={C.accentBg} />
                <Tile label="Median (typical)" value={fmtDur(a.median)} sub="half faster/slower" color={C.green} />
                <Tile label="Total leads" value={fmtNum(a.total)} sub="net-new inbound" />
                <Tile label="Response rate" value={fmtPct(a.rate)} sub={`${a.responded} reached`} color={C.blue} />
                <Tile label="No response" value={fmtNum(a.noResp)} sub="never called/texted" color={a.noResp ? C.red : C.faint} bg={a.noResp ? C.redBg : undefined} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16, marginBottom: 16 }}>
                <Card>
                    <Label right={<span style={{ fontSize: 11, color: C.faint }}>fastest avg first · {clock === "bh" ? "business hrs" : "raw"}</span>}>Rep performance</Label>
                    <div style={{ display: "grid", gridTemplateColumns: "1.3fr 0.9fr 0.6fr 0.7fr 0.9fr 0.9fr", gap: 8, padding: "0 4px 6px" }}>
                        {["Rep", "Lead share", "Leads", "No resp", "Avg", "Median"].map((h, i) => (
                            <div key={h} style={{ fontSize: 10, fontWeight: 600, color: C.faint, textTransform: "uppercase", letterSpacing: "0.05em", textAlign: i === 0 ? "left" : "right" }}>{h}</div>
                        ))}
                    </div>
                    {a.perRep.map((r: any) => {
                        const un = r.rep === "Unassigned"
                        if (!un) repIdx++
                        const col = un ? C.faint : REP_COLORS[repIdx % REP_COLORS.length]
                        return (
                            <div key={r.rep} style={{ display: "grid", gridTemplateColumns: "1.3fr 0.9fr 0.6fr 0.7fr 0.9fr 0.9fr", gap: 8, padding: "9px 4px", alignItems: "center", borderTop: `1px solid ${C.border}` }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                    <div style={{ width: 26, height: 26, borderRadius: "50%", background: col, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{r.rep.charAt(0)}</div>
                                    <span style={{ fontWeight: 600, fontSize: 13 }}>{r.rep.split(" ")[0]}</span>
                                </div>
                                <div style={{ textAlign: "right" }}>
                                    <div style={{ fontSize: 12, fontWeight: 700 }}>{fmtPct(r.share)}</div>
                                    <div style={{ height: 4, background: C.bg, borderRadius: 3, marginTop: 3 }}><div style={{ height: "100%", width: `${Math.round(r.share)}%`, background: col, borderRadius: 3 }} /></div>
                                </div>
                                <div style={{ textAlign: "right", fontSize: 13, fontWeight: 600 }}>{fmtNum(r.leads)}</div>
                                <div style={{ textAlign: "right", fontSize: 13, fontWeight: 700, color: r.noResp ? C.red : C.faint }}>{r.noResp || "0"}</div>
                                <div style={{ textAlign: "right", fontSize: 13, fontWeight: 800, fontFamily: "'Sora', sans-serif", color: C.accent }}>{fmtDur(r.avg)}</div>
                                <div style={{ textAlign: "right", fontSize: 13, fontWeight: 700, color: C.green }}>{fmtDur(r.median)}</div>
                            </div>
                        )
                    })}
                    <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.border}`, fontSize: 12, color: C.muted }}>
                        First touch: <b style={{ color: C.text }}>{a.calls}</b> calls ({fmtPct(pct(a.calls, a.calls + a.texts))}) · <b style={{ color: C.text }}>{a.texts}</b> texts
                    </div>
                </Card>

                <Card>
                    <Label>Typical time to response</Label>
                    <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                        <div style={{ flex: 1, background: C.accentBg, borderRadius: 10, padding: "10px 12px" }}>
                            <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Average</div>
                            <div style={{ fontSize: 19, fontFamily: "'Sora', sans-serif", fontWeight: 800, color: C.accent }}>{fmtDur(a.avg)}</div>
                            <div style={{ fontSize: 11, color: C.faint }}>pulled up by outliers</div>
                        </div>
                        <div style={{ flex: 1, background: C.greenBg, borderRadius: 10, padding: "10px 12px" }}>
                            <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Median</div>
                            <div style={{ fontSize: 19, fontFamily: "'Sora', sans-serif", fontWeight: 800, color: C.green }}>{fmtDur(a.median)}</div>
                            <div style={{ fontSize: 11, color: C.faint }}>what a typical lead waits</div>
                        </div>
                    </div>
                    {a.dist.map((v: number, i: number) => (
                        <div key={i} style={{ marginBottom: 8 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
                                <span style={{ color: C.muted, fontWeight: 500 }}>{s.buckets[i]}</span>
                                <span style={{ color: C.text, fontWeight: 700 }}>{v}<span style={{ color: C.faint, fontWeight: 400 }}> · {fmtPct(pct(v, distTot))}</span></span>
                            </div>
                            <div style={{ height: 8, background: C.bg, borderRadius: 6 }}><div style={{ height: "100%", width: `${Math.max(2, Math.round(pct(v, distPeak)))}%`, background: BUCKET_COLORS[i], borderRadius: 6 }} /></div>
                        </div>
                    ))}
                </Card>
            </div>

            <Card>
                <Label right={<span style={{ fontSize: 11, color: C.faint }}>{tz}</span>}>Lead arrival — day × hour</Label>
                <div style={{ display: "flex", gap: 2, marginBottom: 2, paddingLeft: 32 }}>
                    {HOURS.filter((h) => h % 3 === 0).map((h) => <div key={h} style={{ flex: "3 0 0", fontSize: 9, color: C.faint, textAlign: "center" }}>{fmtH(h)}</div>)}
                </div>
                {s.days.map((day: string, di: number) => (
                    <div key={day} style={{ display: "flex", alignItems: "center", gap: 2, marginBottom: 2 }}>
                        <div style={{ width: 28, fontSize: 10, color: C.faint, textAlign: "right", paddingRight: 4, flexShrink: 0 }}>{day}</div>
                        {HOURS.map((h) => <div key={h} title={`${day} ${fmtH(h)}: ${heat[di][h]} leads`} style={{ flex: 1, aspectRatio: "1", borderRadius: 2, background: heatColor(heat[di][h]), minWidth: 7 }} />)}
                    </div>
                ))}
            </Card>

            <div style={{ fontSize: 11, color: C.faint, marginTop: 14 }}>
                Lead = contact created · clock stops at first manual call or text (email &amp; automation excluded) · updated {new Date(s.meta.generated_ms).toLocaleString()}
            </div>
        </div>
    )
}

addPropertyControls(SpeedToLead, {
    dataUrl: { type: ControlType.String, title: "Data URL", defaultValue: "https://zach-autothat.github.io/royalty-speed-to-lead/summary.json" },
})
