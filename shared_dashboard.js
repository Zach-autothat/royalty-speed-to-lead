/* Speed-to-Lead dashboard rendering — vanilla JS, no dependencies.
 * Powers out/dashboard.html. The Framer component mirrors this logic in React.
 * Input shape: { meta, leads:[{anchor_ms,response_ms,responded,rep_id,rep_name,
 *                channel,raw_seconds,bh_seconds,name,contactId}] }
 */
var STL = (function () {
  var DAY = 86400000;

  function fmtDur(s) {
    if (s === null || s === undefined) return "—";
    s = Math.round(s);
    if (s < 60) return s + "s";
    var m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return m + "m " + r + "s";
    var h = Math.floor(m / 60); m = m % 60;
    if (h < 24) return h + "h " + m + "m";
    var d = Math.floor(h / 24); h = h % 24;
    return d + "d " + h + "h";
  }
  function median(a) {
    if (!a.length) return null;
    var b = a.slice().sort(function (x, y) { return x - y; });
    var i = Math.floor(b.length / 2);
    return b.length % 2 ? b[i] : (b[i - 1] + b[i]) / 2;
  }
  function avg(a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : null; }

  function filterRange(leads, sel, now) {
    if (sel.kind === "all") return leads;
    if (sel.kind === "days") {
      var from = now - sel.days * DAY;
      return leads.filter(function (l) { return l.anchor_ms >= from; });
    }
    // custom [from,to] in ms
    return leads.filter(function (l) { return l.anchor_ms >= sel.from && l.anchor_ms <= sel.to; });
  }

  function secField(clock) { return clock === "raw" ? "raw_seconds" : "bh_seconds"; }

  function aggregate(leads, clock, tz) {
    var f = secField(clock);
    var responded = leads.filter(function (l) { return l.responded; });
    var times = responded.map(function (l) { return l[f]; });

    var byRep = {};
    leads.forEach(function (l) {
      var k = l.rep_name || "Unassigned";
      (byRep[k] = byRep[k] || []).push(l);
    });
    var perRep = Object.keys(byRep).map(function (k) {
      var g = byRep[k], gr = g.filter(function (l) { return l.responded; });
      var t = gr.map(function (l) { return l[f]; });
      return {
        rep: k, leads: g.length, responded: gr.length, noResponse: g.length - gr.length,
        median: median(t), avg: avg(t),
      };
    }).sort(function (a, b) {
      if (a.median === null) return 1; if (b.median === null) return -1;
      return a.median - b.median;
    });

    // Hour-of-day arrival heatmap in business tz
    var hod = [];
    for (var h = 0; h < 24; h++) hod.push({ hour: h, leads: 0, times: [] });
    leads.forEach(function (l) {
      var d = new Date(l.anchor_ms);
      var hh = parseInt(new Intl.DateTimeFormat("en-US", { hour: "2-digit", hour12: false, timeZone: tz }).format(d), 10) % 24;
      hod[hh].leads++;
      if (l.responded) hod[hh].times.push(l[f]);
    });
    hod.forEach(function (x) { x.median = median(x.times); });

    return {
      total: leads.length, responded: responded.length, noResponse: leads.length - responded.length,
      responseRate: leads.length ? responded.length / leads.length : null,
      median: median(times), avg: avg(times), perRep: perRep, hod: hod,
    };
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }

  function mount(root, data) {
    var leads = data.leads || [];
    var tz = (data.meta && data.meta.business_hours && data.meta.business_hours.tz) || "America/Chicago";
    var now = (data.meta && data.meta.generated_ms) || Date.now();
    var state = { sel: { kind: "days", days: 30 }, clock: "bh" };

    function render() {
      root.innerHTML = "";
      var filtered = filterRange(leads, state.sel, now);
      var a = aggregate(filtered, state.clock, tz);

      // Header
      var head = el("div", "stl-head");
      head.appendChild(el("div", "stl-title", "Speed to Lead"));
      var bhcfg = data.meta.business_hours;
      head.appendChild(el("div", "stl-sub",
        (data.meta.location || "") + " · business hours " + bhcfg.open + "–" + bhcfg.close +
        " " + tz + " · updated " + new Date(now).toLocaleString()));
      root.appendChild(head);

      // Controls
      var ctrl = el("div", "stl-controls");
      var ranges = [["7d", 7], ["14d", 14], ["30d", 30], ["90d", 90], ["All", "all"]];
      ranges.forEach(function (r) {
        var active = (r[1] === "all" && state.sel.kind === "all") ||
          (state.sel.kind === "days" && state.sel.days === r[1]);
        var b = el("button", "stl-chip" + (active ? " active" : ""), r[0]);
        b.onclick = function () {
          state.sel = r[1] === "all" ? { kind: "all" } : { kind: "days", days: r[1] };
          render();
        };
        ctrl.appendChild(b);
      });
      // Custom range
      var cf = el("input", "stl-date"); cf.type = "date";
      var ct = el("input", "stl-date"); ct.type = "date";
      var go = el("button", "stl-chip", "Custom");
      go.onclick = function () {
        if (!cf.value || !ct.value) return;
        state.sel = { kind: "custom", from: new Date(cf.value).getTime(), to: new Date(ct.value).getTime() + DAY - 1 };
        render();
      };
      ctrl.appendChild(cf); ctrl.appendChild(ct); ctrl.appendChild(go);
      // Clock toggle
      var spacer = el("div", "stl-spacer"); ctrl.appendChild(spacer);
      [["bh", "Business hours"], ["raw", "Raw"]].forEach(function (c) {
        var b = el("button", "stl-chip" + (state.clock === c[0] ? " active" : ""), c[1]);
        b.onclick = function () { state.clock = c[0]; render(); };
        ctrl.appendChild(b);
      });
      root.appendChild(ctrl);

      // KPI cards
      var kpis = el("div", "stl-kpis");
      function card(label, val, sub) {
        var c = el("div", "stl-card");
        c.appendChild(el("div", "stl-kval", val));
        c.appendChild(el("div", "stl-klabel", label));
        if (sub) c.appendChild(el("div", "stl-ksub", sub));
        return c;
      }
      kpis.appendChild(card("Leads", String(a.total)));
      kpis.appendChild(card("Response rate", a.responseRate === null ? "—" : Math.round(a.responseRate * 100) + "%",
        a.responded + " responded"));
      kpis.appendChild(card("Median response", fmtDur(a.median)));
      kpis.appendChild(card("Avg response", fmtDur(a.avg)));
      kpis.appendChild(card("No response", String(a.noResponse), "never manually contacted"));
      root.appendChild(kpis);

      // Per-rep table
      var tableWrap = el("div", "stl-panel");
      tableWrap.appendChild(el("div", "stl-panel-h", "By rep — fastest first (" +
        (state.clock === "bh" ? "business-hours" : "raw") + " median)"));
      var t = el("table", "stl-table");
      t.innerHTML = "<thead><tr><th>Rep</th><th>Leads</th><th>Responded</th>" +
        "<th>No response</th><th>Median</th><th>Avg</th></tr></thead>";
      var tb = el("tbody");
      a.perRep.forEach(function (r) {
        var tr = el("tr");
        tr.innerHTML = "<td>" + r.rep + "</td><td>" + r.leads + "</td><td>" + r.responded +
          "</td><td>" + (r.noResponse ? "<span class='stl-warn'>" + r.noResponse + "</span>" : "0") +
          "</td><td><b>" + fmtDur(r.median) + "</b></td><td>" + fmtDur(r.avg) + "</td>";
        tb.appendChild(tr);
      });
      t.appendChild(tb); tableWrap.appendChild(t); root.appendChild(tableWrap);

      // Hour-of-day chart
      var hp = el("div", "stl-panel");
      hp.appendChild(el("div", "stl-panel-h", "Lead arrival by hour (" + tz + ")"));
      var chart = el("div", "stl-hod");
      var peak = Math.max.apply(null, a.hod.map(function (x) { return x.leads; }).concat([1]));
      a.hod.forEach(function (x) {
        var col = el("div", "stl-hod-col");
        var bar = el("div", "stl-hod-bar");
        bar.style.height = (x.leads ? Math.max(4, Math.round(90 * x.leads / peak)) : 0) + "px";
        bar.title = x.leads + " leads · median " + fmtDur(x.median);
        col.appendChild(bar);
        col.appendChild(el("div", "stl-hod-lbl", String(x.hour)));
        chart.appendChild(col);
      });
      hp.appendChild(chart);
      hp.appendChild(el("div", "stl-foot",
        "Lead = contact created · clock stops at first MANUAL call or text · email & automation excluded"));
      root.appendChild(hp);
    }

    render();
  }

  return { mount: mount, aggregate: aggregate, fmtDur: fmtDur, filterRange: filterRange };
})();
if (typeof module !== "undefined") module.exports = STL;
