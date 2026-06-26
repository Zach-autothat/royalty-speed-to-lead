// Royalty Rep Scorecard — sheet-bound Apps Script (render engine).
// ---------------------------------------------------------------------------
// The weekly job POSTs one flat table (rep x grain x period x metrics). This
// script stores it (hidden _data tab) and renders readable pages:
//   * one tab per rep  — selected period vs previous (This / Last / Change) vs
//                        editable Targets, + a speed trend sparkline
//   * "Compare all"    — every rep for the selected grain, with up/down arrows
//   * "Targets"        — editable thresholds that drive the status lights
// A Week/Month/Year dropdown (cell F1) on each page re-renders instantly via
// onEdit — no job re-run needed.
//
// Paste this, Save, then Deploy > Manage deployments > edit (pencil) >
// Version: New version > Deploy. The web-app URL stays the same.

var TOKEN = "rylty-sc-Kp93Qz7m";

var GREEN = "#188038", RED = "#c5221f", AMBER = "#b06000", GRAY = "#9aa0a6", MUTE = "#5f6368";
var STATUS_BG = { "On track": "#d9ead3", "Watch": "#fff2cc", "Off track": "#f4cccc", "Low volume": "#efefef" };

var METRICS = [
  { key: "leads", label: "Leads handled", group: "Activity", kind: "int" },
  { key: "median_stl_min", label: "Speed to lead", group: "Activity", kind: "min", t: "Median speed-to-lead (min)", dir: "lo" },
  { key: "nocontact_pct", label: "No-contact leads", group: "Activity", kind: "pct", t: "No-contact leads (%)", dir: "lo" },
  { key: "dials", label: "Dials", group: "Activity", kind: "int" },
  { key: "answer_pct", label: "Answer rate", group: "Activity", kind: "pct", t: "Answer rate (%)", dir: "hi" },
  { key: "texts", label: "Texts", group: "Activity", kind: "int" },
  { key: "touches_per_lead", label: "Touches / lead", group: "Activity", kind: "dec" },
  { key: "calls_scored", label: "Calls scored", group: "Call quality", kind: "int" },
  { key: "avg_score", label: "Avg call score", group: "Call quality", kind: "int", t: "Avg call score", dir: "hi" },
  { key: "qual_avg", label: "Qualification /7", group: "Call quality", kind: "dec", t: "Qualification /7", dir: "hi" },
  { key: "nextstep_pct", label: "Next-step booked", group: "Call quality", kind: "pct", t: "Next-step booked (%)", dir: "hi" }
];
var COMPARE_KEYS = ["leads", "median_stl_min", "nocontact_pct", "dials", "avg_score", "qual_avg"];
var DEFAULT_TARGETS = [
  ["Median speed-to-lead (min)", 15, "lower is better", "First manual call/text. Faster is better."],
  ["No-contact leads (%)", 5, "lower is better", "Leads never called or texted. Should be near zero."],
  ["Answer rate (%)", 70, "higher is better", "Dials that connected."],
  ["Avg call score", 70, "higher is better", "Call Intel score vs the playbook (0-100)."],
  ["Qualification /7", 5, "higher is better", "Tier-1 questions asked on intro calls."],
  ["Next-step booked (%)", 40, "higher is better", "Calls that ended with a booked next step."]
];

function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function doGet(e) {
  if (!e || e.parameter.token !== TOKEN) return out_({ error: "unauthorized" });
  return out_({ ok: true, targets: ensureTargets_(SpreadsheetApp.getActiveSpreadsheet()).getDataRange().getValues() });
}

function doPost(e) {
  var body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ error: "bad json" }); }
  if (!body || body.token !== TOKEN) return out_({ error: "unauthorized" });
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureTargets_(ss);
  storeData_(ss, body.metricKeys || [], body.data || []);
  var reps = body.reps || [];
  renderAll_(ss, reps);
  return out_({ ok: true, reps: reps.length, rows: (body.data || []).length });
}

function storeData_(ss, metricKeys, rows) {
  var sh = ss.getSheetByName("_data") || ss.insertSheet("_data");
  sh.clear();
  var header = ["Rep", "Grain", "Period"].concat(metricKeys);
  var grid = [header].concat(rows);
  sh.getRange(1, 1, grid.length, header.length).setValues(grid);
  sh.hideSheet();
}

function ensureTargets_(ss) {
  var sh = ss.getSheetByName("Targets");
  if (!sh) {
    sh = ss.insertSheet("Targets");
    var rows = [["Metric", "Target", "Direction", "Notes"]].concat(DEFAULT_TARGETS);
    sh.getRange(1, 1, rows.length, 4).setValues(rows);
    sh.setFrozenRows(1);
    sh.setColumnWidth(1, 220);
    sh.setColumnWidth(4, 340);
  }
  return sh;
}

function getTargets_() {
  var v = ensureTargets_(SpreadsheetApp.getActiveSpreadsheet()).getDataRange().getValues();
  var map = {};
  for (var i = 1; i < v.length; i++) if (v[i][0] !== "") map[v[i][0]] = Number(v[i][1]);
  return map;
}

function getSeries_(repFull, grain) {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("_data");
  if (!sh) return [];
  var v = sh.getDataRange().getValues(), keys = v[0].slice(3), out = [];
  for (var i = 1; i < v.length; i++) {
    if (v[i][0] === repFull && v[i][1] === grain) {
      var vals = {};
      for (var k = 0; k < keys.length; k++) { var c = v[i][3 + k]; vals[keys[k]] = (c === "" || c === null) ? null : Number(c); }
      out.push({ period: String(v[i][2]), vals: vals });
    }
  }
  out.sort(function (a, b) { return a.period < b.period ? -1 : (a.period > b.period ? 1 : 0); });
  return out;
}

function repNames_() {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("_data");
  if (!sh) return [];
  var v = sh.getDataRange().getValues(), seen = {}, out = [];
  for (var i = 1; i < v.length; i++) if (!seen[v[i][0]]) { seen[v[i][0]] = 1; out.push(v[i][0]); }
  return out;
}

// ---- formatting helpers --------------------------------------------------
function fmtVal_(m, v) {
  if (v === null || v === "" || v === undefined) return "—";
  if (m.kind === "min") return Math.round(v) + "m";
  if (m.kind === "pct") return Math.round(v) + "%";
  if (m.kind === "dec") return Math.round(v * 10) / 10;
  return Math.round(v);
}
function deltaInfo_(m, t, l) {
  if (t === null || l === null || t === undefined || l === undefined) return { str: "", good: "neutral" };
  var d = t - l, arrow = d > 0 ? "▲" : (d < 0 ? "▼" : "–");
  var unit = m.kind === "pct" ? "pp" : (m.kind === "min" ? "m" : "");
  var ad = m.kind === "dec" ? Math.round(Math.abs(d) * 10) / 10 : Math.round(Math.abs(d));
  var good = "neutral";
  if (m.dir && d !== 0) good = ((m.dir === "lo") ? d < 0 : d > 0) ? "good" : "bad";
  return { str: d === 0 ? "– 0" : arrow + " " + ad + unit, good: good };
}
function targetStr_(m, targets) {
  if (!m.t || targets[m.t] === undefined) return "—";
  var unit = m.kind === "pct" ? "%" : (m.kind === "min" ? "m" : "");
  return (m.dir === "lo" ? "≤" : "≥") + targets[m.t] + unit;
}
function metricMeet_(m, v, targets) {
  if (!m.t || v === null || v === undefined || targets[m.t] === undefined) return "";
  return ((m.dir === "lo") ? v <= targets[m.t] : v >= targets[m.t]) ? "ok" : "miss";
}
function computeStatus_(vals, targets) {
  var leads = vals["leads"] || 0, calls = vals["calls_scored"] || 0;
  if (leads < 8 && calls < 3) return "Low volume";
  var core = [["median_stl_min", "Median speed-to-lead (min)", "lo"], ["nocontact_pct", "No-contact leads (%)", "lo"],
  ["avg_score", "Avg call score", "hi"], ["qual_avg", "Qualification /7", "hi"]], br = 0;
  core.forEach(function (c) {
    var v = vals[c[0]], tt = targets[c[1]];
    if (v === null || v === undefined || tt === undefined) return;
    if (!((c[2] === "lo") ? v <= tt : v >= tt)) br++;
  });
  return br === 0 ? "On track" : (br === 1 ? "Watch" : "Off track");
}
function pretty_(grain, period) {
  if (!period) return "—";
  if (grain === "Year") return period;
  if (grain === "Week") { var p = period.split("-W"); return "Wk " + Number(p[1]) + " '" + p[0].slice(2); }
  var mn = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var q = period.split("-"); return mn[Number(q[1])] + " " + q[0];
}
function paintStatus_(cell, status) {
  cell.setBackground(STATUS_BG[status] || "#ffffff");
  cell.setFontColor(status === "Off track" ? RED : (status === "Watch" ? AMBER : (status === "On track" ? GREEN : MUTE)));
  cell.setFontWeight("bold");
}
function grainOf_(sh) {
  try { var g = sh.getRange("F1").getValue(); if (g === "Week" || g === "Month" || g === "Year") return g; } catch (e) {}
  return "Month";
}
function setDropdown_(sh, grain) {
  var rule = SpreadsheetApp.newDataValidation().requireValueInList(["Week", "Month", "Year"], true).build();
  sh.getRange("E1").setValue("Period").setFontColor(GRAY).setHorizontalAlignment("right");
  sh.getRange("F1").setDataValidation(rule).setValue(grain).setHorizontalAlignment("center").setFontWeight("bold");
}

// ---- rendering -----------------------------------------------------------
function renderRep_(sh, repFull, grain) {
  grain = grain || "Month";
  var targets = getTargets_(), series = getSeries_(repFull, grain);
  var thisP = series.length ? series[series.length - 1] : null;
  var lastP = series.length > 1 ? series[series.length - 2] : null;
  sh.clear();
  sh.getRange("Z1").setValue("rep:" + repFull);
  sh.getRange("A1").setValue(repFull).setFontWeight("bold").setFontSize(14);
  sh.getRange("A2").setValue("Sales rep · updated weekly").setFontColor(GRAY).setFontSize(10);
  setDropdown_(sh, grain);
  var ov = thisP ? computeStatus_(thisP.vals, targets) : "—";
  paintStatus_(sh.getRange("F2").setValue(ov).setHorizontalAlignment("center"), ov);
  sh.getRange("A3").setValue(thisP
    ? "Change = " + pretty_(grain, thisP.period) + " vs " + (lastP ? pretty_(grain, lastP.period) : "—") + "   ·   green improved / red worse"
    : "No data yet").setFontColor(GRAY).setFontSize(10);

  var head = ["Metric", "This" + (thisP ? " (" + pretty_(grain, thisP.period) + ")" : ""),
    "Last" + (lastP ? " (" + pretty_(grain, lastP.period) + ")" : ""), "Change", "Target", "vs tgt"];
  sh.getRange(4, 1, 1, 6).setValues([head]).setFontWeight("bold").setFontColor(MUTE).setFontSize(10);
  sh.getRange(4, 2, 1, 4).setHorizontalAlignment("right");
  sh.getRange(4, 6).setHorizontalAlignment("center");

  var r = 5, lastGroup = "";
  METRICS.forEach(function (m) {
    if (m.group !== lastGroup) {
      sh.getRange(r, 1).setValue(m.group.toUpperCase()).setFontColor(GRAY).setFontSize(9).setFontWeight("bold");
      lastGroup = m.group; r++;
    }
    var tv = thisP ? thisP.vals[m.key] : null, lv = lastP ? lastP.vals[m.key] : null;
    var ch = deltaInfo_(m, tv, lv), st = metricMeet_(m, tv, targets);
    sh.getRange(r, 1, 1, 6).setValues([[m.label, fmtVal_(m, tv), fmtVal_(m, lv), ch.str, targetStr_(m, targets), st ? "●" : ""]]);
    sh.getRange(r, 2, 1, 4).setHorizontalAlignment("right");
    sh.getRange(r, 5).setFontColor(GRAY);
    sh.getRange(r, 6).setHorizontalAlignment("center");
    sh.getRange(r, 4).setFontColor(ch.good === "good" ? GREEN : (ch.good === "bad" ? RED : GRAY));
    if (st) sh.getRange(r, 6).setFontColor(st === "ok" ? GREEN : AMBER);
    if (st === "miss") sh.getRange(r, 2).setFontColor(AMBER).setFontWeight("bold");
    r++;
  });

  try {
    r += 1;
    var hist = series.slice(-8).map(function (p) { return p.vals["median_stl_min"]; });
    sh.getRange(r, 1).setValue("Speed to lead — last " + hist.length + " " + grain.toLowerCase() + "s")
      .setFontColor(MUTE).setFontSize(10).setFontWeight("bold");
    if (hist.length) {
      sh.getRange(r + 1, 10, 1, hist.length).setValues([hist.map(function (x) { return x === null ? "" : x; })]);
      var a = colA_(10) + (r + 1), b = colA_(10 + hist.length - 1) + (r + 1);
      sh.getRange(r + 1, 2).setFormula('=SPARKLINE(' + a + ':' + b + ',{"charttype","column";"color","' + AMBER + '"})');
    }
    sh.hideColumns(8, 19);
  } catch (err) {}

  sh.setColumnWidth(1, 155);
  [2, 3, 4, 5, 6].forEach(function (c) { sh.setColumnWidth(c, 96); });
  sh.setFrozenRows(4);
  sh.getRange("A1").activate();
}

function renderCompare_(sh, grain, reps) {
  grain = grain || "Month";
  var targets = getTargets_();
  sh.clear();
  sh.getRange("Z1").setValue("compare");
  sh.getRange("A1").setValue("Team comparison").setFontWeight("bold").setFontSize(14);
  setDropdown_(sh, grain);

  var labels = { leads: "Leads", median_stl_min: "Speed", nocontact_pct: "No-contact", dials: "Dials", avg_score: "Avg score", qual_avg: "Qual /7" };
  var head = ["Rep"].concat(COMPARE_KEYS.map(function (k) { return labels[k]; })).concat(["Status"]);
  var rank = { "Off track": 0, "Watch": 1, "On track": 2, "Low volume": 3 };
  var rows = reps.map(function (rep) {
    var s = getSeries_(rep, grain);
    var tp = s.length ? s[s.length - 1] : null, lp = s.length > 1 ? s[s.length - 2] : null;
    return { rep: rep, tp: tp, lp: lp, status: tp ? computeStatus_(tp.vals, targets) : "—" };
  }).sort(function (a, b) { return (rank[a.status] - rank[b.status]) || (a.rep < b.rep ? -1 : 1); });

  var period = rows.length && rows[0].tp ? pretty_(grain, rows[0].tp.period) : "—";
  sh.getRange("A2").setValue(grain + " · " + period + " vs previous   ·   arrows compare to the rep's last " + grain.toLowerCase())
    .setFontColor(GRAY).setFontSize(10);
  sh.getRange(4, 1, 1, head.length).setValues([head]).setFontWeight("bold").setFontColor(MUTE).setFontSize(10);
  sh.getRange(4, 2, 1, head.length - 1).setHorizontalAlignment("right");

  var r = 5;
  rows.forEach(function (row) {
    var line = [row.rep.split(" ")[0]], goods = [];
    COMPARE_KEYS.forEach(function (k) {
      var m = mByKey_(k);
      var tv = row.tp ? row.tp.vals[k] : null, lv = row.lp ? row.lp.vals[k] : null;
      var ch = deltaInfo_(m, tv, lv);
      line.push(fmtVal_(m, tv) + (ch.str && m.dir ? "  " + ch.str.split(" ")[0] : ""));
      goods.push(ch.good);
    });
    line.push(row.status);
    sh.getRange(r, 1, 1, line.length).setValues([line]);
    sh.getRange(r, 2, 1, COMPARE_KEYS.length).setHorizontalAlignment("right");
    for (var i = 0; i < COMPARE_KEYS.length; i++)
      sh.getRange(r, 2 + i).setFontColor(goods[i] === "good" ? GREEN : (goods[i] === "bad" ? RED : "#202124"));
    paintStatus_(sh.getRange(r, 2 + COMPARE_KEYS.length).setHorizontalAlignment("right"), row.status);
    r++;
  });

  sh.setColumnWidth(1, 110);
  for (var c = 2; c <= head.length; c++) sh.setColumnWidth(c, 96);
  sh.setFrozenRows(4);
  sh.hideColumns(8, 19);
  sh.getRange("A1").activate();
}

function mByKey_(k) { for (var i = 0; i < METRICS.length; i++) if (METRICS[i].key === k) return METRICS[i]; return { kind: "int" }; }
function colA_(col) { var s = ""; while (col > 0) { var m = (col - 1) % 26; s = String.fromCharCode(65 + m) + s; col = (col - m - 1) / 26; } return s; }

function renderAll_(ss, reps) {
  // Compare tab first.
  var cmp = ss.getSheetByName("Compare all") || ss.insertSheet("Compare all");
  renderCompare_(cmp, grainOf_(cmp), reps);
  ss.setActiveSheet(cmp); ss.moveActiveSheet(1);

  var used = { "Compare all": 1 }, idx = 2;
  reps.forEach(function (rep) {
    var name = rep.split(" ")[0]; if (used[name]) name = rep; used[name] = 1;
    var sh = ss.getSheetByName(name) || ss.insertSheet(name);
    renderRep_(sh, rep, grainOf_(sh));
    ss.setActiveSheet(sh); ss.moveActiveSheet(idx++);
  });
  var tg = ss.getSheetByName("Targets"); if (tg) { ss.setActiveSheet(tg); ss.moveActiveSheet(idx++); }
  var s1 = ss.getSheetByName("Sheet1"); if (s1 && ss.getSheets().length > 1) { try { ss.deleteSheet(s1); } catch (x) {} }
}

// Live dropdown: re-render the page whose F1 (period) was changed.
function onEdit(e) {
  try {
    if (!e || !e.range || e.range.getA1Notation() !== "F1") return;
    var sh = e.range.getSheet(), marker = String(sh.getRange("Z1").getValue());
    if (marker.indexOf("rep:") === 0) renderRep_(sh, marker.slice(4), e.value);
    else if (marker === "compare") renderCompare_(sh, e.value, repNames_());
  } catch (err) {}
}
