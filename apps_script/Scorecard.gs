// Royalty Rep Scorecard — sheet-bound Apps Script web app.
// ---------------------------------------------------------------------------
// Lives INSIDE the Google Sheet (Extensions > Apps Script). Runs as the sheet
// owner, so there is no service account, no key, no IAM/admin policy involved.
// The daily job GETs the editable Targets tab and POSTs the computed grids;
// this script writes them into tabs and colors the Status column.
//
// Deploy: Extensions > Apps Script > paste this > Deploy > New deployment >
//   type "Web app" > Execute as: Me · Who has access: Anyone > Deploy
//   (authorize when prompted). Copy the "Web app" URL — that's SCORECARD_WEBAPP_URL.
//
// Set TOKEN below to a private string and use the SAME value as SCORECARD_TOKEN
// in the job. It's a simple shared secret so only the job can write.

var TOKEN = "REPLACE_WITH_YOUR_TOKEN";

var DEFAULT_TARGETS = [
  ["Median speed-to-lead (min)", 15, "lower is better", "First manual call/text. Faster is better."],
  ["No-contact leads (%)", 5, "lower is better", "Leads never called or texted. Should be near zero."],
  ["Answer rate (%)", 70, "higher is better", "Dials that connected."],
  ["Avg call score", 70, "higher is better", "Call Intel score vs the playbook (0-100)."],
  ["Qualification /7", 5, "higher is better", "Tier-1 questions asked on intro calls."],
  ["Next-step booked (%)", 40, "higher is better", "Calls that ended with a booked next step."]
];

var STATUS_COLORS = {
  "On track": "#d9ead3", "Watch": "#fff2cc", "Off track": "#f4cccc", "Low volume": "#efefef"
};

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

function doGet(e) {
  if (!e || e.parameter.token !== TOKEN) return out_({ error: "unauthorized" });
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return out_({ targets: ensureTargets_(ss).getDataRange().getValues() });
}

function doPost(e) {
  var body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ error: "bad json" }); }
  if (!body || body.token !== TOKEN) return out_({ error: "unauthorized" });
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureTargets_(ss);
  var tabs = body.tabs || {}, written = {};
  Object.keys(tabs).forEach(function (name) {
    var grid = tabs[name] || [];
    var sh = ss.getSheetByName(name) || ss.insertSheet(name);
    sh.clear();
    if (grid.length) {
      sh.getRange(1, 1, grid.length, grid[0].length).setValues(grid);
      sh.setFrozenRows(1);
      colorStatus_(sh, grid);
    }
    written[name] = grid.length ? grid.length - 1 : 0;
  });
  cleanup_(ss);
  return out_({ ok: true, written: written });
}

function colorStatus_(sh, grid) {
  var col = grid[0].indexOf("Status");
  if (col < 0) return;
  for (var r = 1; r < grid.length; r++) {
    var c = STATUS_COLORS[grid[r][col]];
    if (c) sh.getRange(r + 1, col + 1).setBackground(c);
  }
}

function cleanup_(ss) {
  var order = { "Scorecard": 1, "Weekly": 2, "Monthly": 3, "Yearly": 4, "Targets": 5 };
  var s1 = ss.getSheetByName("Sheet1");
  if (s1 && ss.getSheets().length > 1) { try { ss.deleteSheet(s1); } catch (x) {} }
  Object.keys(order).forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (sh) { ss.setActiveSheet(sh); ss.moveActiveSheet(order[name]); }
  });
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
