"""Generate static company-facts.html from seed JSON."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "app" / "static" / "company-facts-data.json"
OUT_PATH = ROOT / "app" / "static" / "company-facts.html"

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ampcus Company Facts — Reference</title>
  <style>
    :root {
      --bg: #0f1117;
      --surface: #171a22;
      --surface2: #1e222c;
      --stroke: #2a3040;
      --text: #e8eaef;
      --muted: #9aa3b5;
      --accent: #6b9fff;
      --accent-dim: #3d5a8a;
      --good: #4ade80;
      --bad: #f87171;
      --radius: 10px;
      --font: "Segoe UI", system-ui, -apple-system, sans-serif;
      --mono: "Cascadia Code", "Consolas", monospace;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: var(--font); background: var(--bg); color: var(--text); line-height: 1.5; }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }
    header { margin-bottom: 2rem; }
    .eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; color: var(--muted); margin: 0 0 .35rem; }
    h1 { margin: 0 0 .5rem; font-size: 1.75rem; font-weight: 600; }
    .lead { color: var(--muted); max-width: 52rem; margin: 0 0 1.5rem; }
    .lead code { font-family: var(--mono); font-size: .88em; color: var(--accent); }
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .75rem; margin-bottom: 1.5rem; }
    .stat { background: var(--surface); border: 1px solid var(--stroke); border-radius: var(--radius); padding: .85rem 1rem; }
    .stat-label { font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
    .stat-value { font-size: 1.5rem; font-weight: 600; margin-top: .15rem; }
    .charts-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1rem;
      margin-bottom: 1.75rem;
    }
    .chart-panel {
      background: var(--surface);
      border: 1px solid var(--stroke);
      border-radius: var(--radius);
      padding: 1rem 1.1rem 1.25rem;
    }
    .chart-panel h2 {
      margin: 0 0 .75rem;
      font-size: .95rem;
      font-weight: 600;
      color: var(--text);
    }
    .chart-wrap { position: relative; height: 260px; }
    .chart-panel-map { display: flex; flex-direction: column; min-height: 360px; }
    .office-map {
      flex: 1;
      min-height: 320px;
      height: 320px;
      border-radius: 8px;
      border: 1px solid var(--stroke);
      background: #12151c;
      z-index: 0;
    }
    .office-map-legend {
      list-style: none;
      margin: .75rem 0 0;
      padding: 0;
      display: flex;
      flex-wrap: wrap;
      gap: .4rem .75rem;
      color: var(--muted);
      font-size: .78rem;
    }
    .office-map-legend li {
      display: inline-flex;
      align-items: center;
      gap: .35rem;
    }
    .office-map-legend .dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--accent); box-shadow: 0 0 0 2px rgba(107,159,255,.25);
    }
    .office-map-legend .dot.hq { background: var(--good); box-shadow: 0 0 0 2px rgba(74,222,128,.25); }
    .office-map-legend .dot.campus { background: #fb923c; box-shadow: 0 0 0 2px rgba(251,146,60,.25); }
    .office-map-legend .note { opacity: .85; }
    .leaflet-container { background: #12151c; font: inherit; }
    .leaflet-tile-pane img { max-width: none !important; }
    .leaflet-popup-content-wrapper {
      background: var(--surface2);
      color: var(--text);
      border-radius: 8px;
      border: 1px solid var(--stroke);
      box-shadow: 0 8px 24px rgba(0,0,0,.35);
    }
    .leaflet-popup-tip { background: var(--surface2); }
    .leaflet-popup-content { margin: .65rem .85rem; font-size: .85rem; line-height: 1.4; }
    .leaflet-popup-content strong { display: block; margin-bottom: .2rem; }
    .leaflet-popup-content .muted { color: var(--muted); font-size: .78rem; }
    .office-pin {
      background: transparent; border: 0;
    }
    .office-pin span {
      display: block;
      width: 14px; height: 14px;
      border-radius: 50% 50% 50% 0;
      transform: rotate(-45deg);
      background: var(--accent);
      border: 2px solid #fff;
      box-shadow: 0 2px 8px rgba(0,0,0,.45);
    }
    .office-pin.hq span { background: var(--good); }
    .office-pin.campus span { background: #fb923c; }
    .toolbar { display: flex; flex-wrap: wrap; gap: .75rem; align-items: center; margin-bottom: 1.25rem; }
    .toolbar input[type=search] {
      flex: 1; min-width: 220px; background: var(--surface2); border: 1px solid var(--stroke);
      color: var(--text); border-radius: 8px; padding: .55rem .85rem; font-size: .95rem;
    }
    .toolbar label { display: flex; align-items: center; gap: .4rem; color: var(--muted); font-size: .9rem; cursor: pointer; }
    .tabs { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: 1.5rem; }
    .tab {
      background: var(--surface); border: 1px solid var(--stroke); color: var(--muted);
      border-radius: 999px; padding: .35rem .85rem; font-size: .85rem; cursor: pointer;
    }
    .tab.active { background: var(--accent-dim); border-color: var(--accent); color: var(--text); }
    .tab .count { opacity: .7; margin-left: .25rem; }
    section.cat-section { margin-bottom: 2.5rem; }
    section.cat-section h2 {
      font-size: 1.1rem; font-weight: 600; margin: 0 0 1rem; padding-bottom: .5rem;
      border-bottom: 1px solid var(--stroke); text-transform: capitalize;
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
    .card {
      background: var(--surface); border: 1px solid var(--stroke); border-radius: var(--radius);
      padding: 1rem 1.1rem; display: flex; flex-direction: column; gap: .65rem;
    }
    .card.inactive { opacity: .65; }
    .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; }
    .card h3 { margin: 0; font-size: 1.05rem; font-weight: 600; }
    .badge {
      font-size: .68rem; text-transform: uppercase; letter-spacing: .05em;
      padding: .15rem .45rem; border-radius: 4px; white-space: nowrap;
      background: var(--surface2); border: 1px solid var(--stroke); color: var(--muted);
    }
    .badge.active { color: var(--good); border-color: #166534; background: #052e16; }
    .badge.inactive { color: var(--bad); border-color: #7f1d1d; background: #2a0a0a; }
    .desc { color: var(--muted); font-size: .92rem; margin: 0; }
    .detail-line { font-size: .88rem; margin: 0; }
    .attrs {
      margin: 0; padding: 0; list-style: none;
      display: grid; grid-template-columns: 1fr 1fr; gap: .35rem .75rem; font-size: .82rem;
    }
    .attrs li { display: flex; flex-direction: column; gap: .1rem; }
    .attrs .k { color: var(--muted); font-size: .72rem; text-transform: capitalize; }
    .attrs .v { font-family: var(--mono); font-size: .78rem; word-break: break-word; }
    footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--stroke); color: var(--muted); font-size: .82rem; }
    footer code { font-family: var(--mono); font-size: .85em; }
    @media print {
      body { background: #fff; color: #111; }
      .card, .stat { border-color: #ccc; background: #fff; }
      .toolbar, .tabs { display: none; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <p class="eyebrow">Ampcus Helpdesk · NLP data source</p>
      <h1>Company Facts Database</h1>
      <p class="lead">Complete reference of the <code>company_facts</code> table — clients, services, locations, products, team, and partnerships. Used by the Company Data NLP pipeline for employee queries.</p>
      <div class="stats" id="stats"></div>
      <div class="charts-row">
        <article class="chart-panel">
          <h2>Rows by category</h2>
          <div class="chart-wrap"><canvas id="chart-categories" aria-label="Rows by category"></canvas></div>
        </article>
        <article class="chart-panel chart-panel-map">
          <h2>Office locations</h2>
          <div id="office-map" class="office-map" role="img" aria-label="Office locations map"></div>
          <ul id="office-map-legend" class="office-map-legend"></ul>
        </article>
      </div>
    </header>
    <div class="toolbar">
      <input type="search" id="search" placeholder="Search name, description, attributes…" autocomplete="off" />
      <label><input type="checkbox" id="active-only" checked /> Active only</label>
    </div>
    <div class="tabs" id="tabs"></div>
    <div id="content"></div>
    <footer>
      Ampcus Helpdesk seed data · __RECORD_COUNT__ records · SQLite table <code>company_facts</code> in <code>audit.db</code>
    </footer>
  </div>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script>
    const DATA = __DATA_JSON__;
    const CHART_COLORS = ['#4ade80', '#60a5fa', '#6366f1', '#fb923c', '#c2410c', '#fbbf24'];
    const fmt = (k) => k.replace(/_/g, ' ');
    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function matches(f, q) {
      if (!q) return true;
      const blob = [f.name, f.description, f.detail_1, f.detail_2, f.category,
        ...Object.entries(f.attributes||{}).flatMap(([k,v])=>[k,String(v)])].join(' ').toLowerCase();
      return blob.includes(q);
    }
    function renderStats() {
      const el = document.getElementById('stats');
      const active = DATA.facts.filter(f=>f.active).length;
      el.innerHTML = [
        ['Total records', DATA.facts.length],
        ['Active', active],
        ['Inactive', DATA.facts.length - active],
        ['Categories', DATA.categories.length],
      ].map(([l,v])=>'<article class="stat"><p class="stat-label">'+l+'</p><p class="stat-value">'+v+'</p></article>').join('');
    }
    function renderTabs(activeCat) {
      const el = document.getElementById('tabs');
      const counts = Object.fromEntries(DATA.categories.map(c=>[c, DATA.facts.filter(f=>f.category===c).length]));
      el.innerHTML = ['all', ...DATA.categories].map(c => {
        const n = c==='all' ? DATA.facts.length : counts[c];
        const cls = (activeCat===c) ? 'tab active' : 'tab';
        return '<button type="button" class="'+cls+'" data-cat="'+c+'">'+fmt(c)+'<span class="count">('+n+')</span></button>';
      }).join('');
      el.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => { state.cat = btn.dataset.cat; render(); }));
    }
    const state = { cat: 'all', q: '', activeOnly: true };
    function renderCards() {
      const q = state.q.trim().toLowerCase();
      let facts = DATA.facts.filter(f => {
        if (state.activeOnly && !f.active) return false;
        if (state.cat !== 'all' && f.category !== state.cat) return false;
        return matches(f, q);
      });
      const byCat = {};
      for (const c of DATA.categories) byCat[c] = facts.filter(f=>f.category===c);
      const content = document.getElementById('content');
      if (!facts.length) {
        content.innerHTML = '<p class="desc">No facts match your filters.</p>';
        return;
      }
      const cats = state.cat === 'all' ? DATA.categories.filter(c => byCat[c].length) : [state.cat];
      content.innerHTML = cats.map(cat => {
        const items = byCat[cat];
        return '<section class="cat-section"><h2>'+fmt(cat)+' ('+items.length+')</h2><div class="grid">' +
          items.map(f => {
            const attrs = Object.entries(f.attributes||{}).map(([k,v]) =>
              '<li><span class="k">'+fmt(k)+'</span><span class="v">'+esc(v)+'</span></li>').join('');
            return '<article class="card'+(f.active?'':' inactive')+'">' +
              '<div class="card-head"><h3>'+esc(f.name)+'</h3>' +
              '<span class="badge '+(f.active?'active':'inactive')+'">'+(f.active?'active':'inactive')+'</span></div>' +
              '<p class="desc">'+esc(f.description)+'</p>' +
              '<p class="detail-line">'+esc(f.detail_1)+'</p>' +
              '<p class="detail-line">'+esc(f.detail_2)+'</p>' +
              (attrs ? '<ul class="attrs">'+attrs+'</ul>' : '') +
              '</article>';
          }).join('') + '</div></section>';
      }).join('');
    }
    function render() { renderTabs(state.cat); renderCards(); }
    document.getElementById('search').addEventListener('input', e => { state.q = e.target.value; renderCards(); });
    document.getElementById('active-only').addEventListener('change', e => { state.activeOnly = e.target.checked; renderCards(); });

    function shortLocation(name) {
      return name
        .replace(' Tech Hub', '')
        .replace(' Delivery Center', '')
        .replace(' Office', '')
        .replace(' Hub', '')
        .replace(' HQ', ' HQ');
    }

    /* City-center coordinates for mappable office locations */
    const LOCATION_COORDS = {
      "Atlanta, GA": [33.749, -84.388],
      "Birmingham, AL": [33.5186, -86.8104],
      "Chantilly, VA": [38.8943, -77.4311],
      "Charlotte, NC": [35.2271, -80.8431],
      "Chicago, IL": [41.8781, -87.6298],
      "Columbus, OH": [39.9612, -82.9988],
      "Dallas, TX": [32.7767, -96.797],
      "Denver, CO": [39.7392, -104.9903],
      "Detroit, MI": [42.3314, -83.0458],
      "Farmington, CT": [41.7198, -72.832],
      "Houston, TX": [29.7604, -95.3698],
      "Jacksonville, FL": [30.3322, -81.6557],
      "Nashik Campus": [19.9975, 73.7898],
      "New York, NY": [40.7128, -74.006],
      "Newark, CA": [37.5297, -122.0402],
      "Owings Mills, MD": [39.4195, -76.7803],
      "Parsippany, NJ": [40.8659, -74.4171],
      "Richmond, VA": [37.5407, -77.436],
      "San Francisco, CA": [37.7749, -122.4194],
      "Washington, DC": [38.9072, -77.0369],
    };

    function pinClass(type) {
      const t = String(type || "").toLowerCase();
      if (t.includes("headquarters")) return "hq";
      if (t.includes("campus")) return "campus";
      return "";
    }

    function renderOfficeMap() {
      const mapEl = document.getElementById("office-map");
      const legendEl = document.getElementById("office-map-legend");
      if (!mapEl || typeof L === "undefined") return;

      const locations = DATA.facts.filter((f) => f.category === "locations" && f.active);
      const pins = [];
      const unmapped = [];

      for (const f of locations) {
        const coords = LOCATION_COORDS[f.name];
        if (!coords) {
          unmapped.push(f);
          continue;
        }
        pins.push({ fact: f, lat: coords[0], lng: coords[1] });
      }

      const map = L.map(mapEl, {
        scrollWheelZoom: false,
        worldCopyJump: true,
      });

      // Esri dark basemap (reliable from localhost); CARTO as fallback if a tile fails.
      const esriDark = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        {
          attribution:
            "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
          maxZoom: 16,
        }
      );
      const cartoDark = L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
          subdomains: "abcd",
          maxZoom: 19,
        }
      );
      let usingFallback = false;
      esriDark.on("tileerror", () => {
        if (usingFallback) return;
        usingFallback = true;
        map.removeLayer(esriDark);
        cartoDark.addTo(map);
      });
      esriDark.addTo(map);

      const bounds = [];
      for (const p of pins) {
        const kind = pinClass(p.fact.attributes?.type);
        const icon = L.divIcon({
          className: "office-pin " + kind,
          html: "<span></span>",
          iconSize: [14, 14],
          iconAnchor: [7, 14],
          popupAnchor: [0, -12],
        });
        const emp = p.fact.attributes?.employee_count;
        const type = p.fact.attributes?.type || "Office";
        const city = p.fact.attributes?.city || "";
        const country = p.fact.attributes?.country || "";
        const place = [city, country].filter(Boolean).join(", ");
        const popup =
          "<strong>" +
          esc(p.fact.name) +
          "</strong>" +
          '<div class="muted">' +
          esc(type) +
          (place ? " · " + esc(place) : "") +
          "</div>" +
          (emp != null && emp !== ""
            ? '<div class="muted">Employees: ' + esc(emp) + "</div>"
            : "") +
          (p.fact.description
            ? '<div class="muted" style="margin-top:.35rem">' +
              esc(p.fact.description) +
              "</div>"
            : "");
        L.marker([p.lat, p.lng], { icon })
          .addTo(map)
          .bindPopup(popup);
        bounds.push([p.lat, p.lng]);
      }

      if (bounds.length) {
        map.fitBounds(bounds, { padding: [28, 28], maxZoom: 5 });
      } else {
        map.setView([39.5, -98], 3);
      }

      // Leaflet sometimes needs a resize after layout
      setTimeout(() => map.invalidateSize(), 50);

      const legendBits = [
        '<li><span class="dot"></span> U.S. office</li>',
        '<li><span class="dot hq"></span> Headquarters</li>',
        '<li><span class="dot campus"></span> Campus</li>',
        '<li class="note">' + pins.length + " pinned</li>",
      ];
      if (unmapped.length) {
        legendBits.push(
          '<li class="note">Also listed (no map pin): ' +
            unmapped.map((f) => esc(f.name)).join(", ") +
            "</li>"
        );
      }
      if (legendEl) legendEl.innerHTML = legendBits.join("");
    }

    function renderCharts() {
      const legendColor = "#e8eaef";

      const catCounts = DATA.categories.map((c) => ({
        label: fmt(c),
        count: DATA.facts.filter((f) => f.category === c).length,
      }));
      new Chart(document.getElementById("chart-categories"), {
        type: "pie",
        data: {
          labels: catCounts.map((c) => c.label),
          datasets: [
            {
              data: catCounts.map((c) => c.count),
              backgroundColor: CHART_COLORS,
              borderColor: "#171a22",
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "right",
              labels: {
                color: legendColor,
                boxWidth: 12,
                padding: 10,
                font: { size: 12 },
              },
            },
            tooltip: {
              callbacks: {
                label(ctx) {
                  const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                  const pct = Math.round((ctx.raw / total) * 100);
                  return `${ctx.label}: ${ctx.raw} (${pct}%)`;
                },
              },
            },
          },
        },
      });

      renderOfficeMap();
    }

    renderStats();
    renderCharts();
    render();
  </script>
</body>
</html>
"""


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__RECORD_COUNT__", str(len(data["facts"])))
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(data['facts'])} facts)")


if __name__ == "__main__":
    main()
