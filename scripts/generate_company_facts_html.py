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
        <article class="chart-panel">
          <h2>Employees by location</h2>
          <div class="chart-wrap"><canvas id="chart-locations" aria-label="Employees by location"></canvas></div>
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
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
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

    function renderCharts() {
      const gridColor = '#2a3040';
      const tickColor = '#9aa3b5';
      const legendColor = '#e8eaef';

      const catCounts = DATA.categories.map(c => ({
        label: fmt(c),
        count: DATA.facts.filter(f => f.category === c).length,
      }));
      new Chart(document.getElementById('chart-categories'), {
        type: 'pie',
        data: {
          labels: catCounts.map(c => c.label),
          datasets: [{
            data: catCounts.map(c => c.count),
            backgroundColor: CHART_COLORS,
            borderColor: '#171a22',
            borderWidth: 2,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'right',
              labels: { color: legendColor, boxWidth: 12, padding: 10, font: { size: 12 } },
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

      const locations = DATA.facts
        .filter(f => f.category === 'locations' && f.active)
        .map(f => ({
          name: shortLocation(f.name),
          employees: Number(f.attributes?.employee_count || 0),
        }))
        .sort((a, b) => b.employees - a.employees);

      new Chart(document.getElementById('chart-locations'), {
        type: 'bar',
        data: {
          labels: locations.map(l => l.name),
          datasets: [{
            label: 'Employees',
            data: locations.map(l => l.employees),
            backgroundColor: locations.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
            borderRadius: 4,
            maxBarThickness: 48,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: (items) => {
                  const idx = items[0]?.dataIndex ?? 0;
                  const full = DATA.facts.find(f => f.category === 'locations' && shortLocation(f.name) === locations[idx]?.name);
                  return full?.name || items[0]?.label || '';
                },
                label(ctx) { return `Employees: ${ctx.raw}`; },
              },
            },
          },
          scales: {
            x: {
              ticks: { color: tickColor, font: { size: 11 } },
              grid: { display: false },
            },
            y: {
              beginAtZero: true,
              suggestedMax: 400,
              ticks: { color: tickColor, stepSize: 100 },
              grid: { color: gridColor },
              title: { display: true, text: 'Employees', color: tickColor, font: { size: 11 } },
            },
          },
        },
      });
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
