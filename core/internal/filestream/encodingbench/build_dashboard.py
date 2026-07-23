"""Build a self-contained HTML dashboard from a parsed benchmark CSV.

    python3 parse_bench.py bench-run.log -o bench.csv
    python3 build_dashboard.py bench.csv -o bench_dashboard.html

No external JS/CSS dependencies: the page is plain HTML/CSS/SVG so it opens
directly from disk (file://) with no server or CDN needed.
"""
import argparse
import csv
import json
import sys

FLOAT_FIELDS = [
    "iterations", "allocs_per_op", "b_per_op", "body_bytes", "cells_per_op",
    "envelope_bytes", "envelope_ratio", "gzip1_bytes", "gzip1_ratio",
    "gzip6_bytes", "gzip6_ratio", "mb_per_s", "ns_per_op", "ops_per_sec", "rows_per_op",
]

DATASET_ORDER = ["tiny", "dense_numeric", "sparse_mixed", "wide_mixed", "nested_json", "system_metrics"]
FORMAT_ORDER = ["legacy_json_jsonl", "json_row_proto_b64", "proto_row_proto", "json_column_proto_b64", "proto_column_proto"]
VALUE_MODE_ORDER = ["value_json_only", "typed_only"]


def load_rows(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            for field in FLOAT_FIELDS:
                if r.get(field):
                    r[field] = float(r[field])
                else:
                    r[field] = None
            rows.append(r)
        return rows


def ordered_uniques(rows, key, preferred):
    seen = list(dict.fromkeys(r[key] for r in rows))
    return [v for v in preferred if v in seen] + [v for v in seen if v not in preferred]


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Filestream encoding benchmark</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --grid:           #e1e0d9;
    --baseline:       #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --series-1: #2a78d6; /* legacy_json_jsonl */
    --series-2: #1baf7a; /* json_row_proto_b64 */
    --series-3: #eda100; /* proto_row_proto */
    --series-4: #4a3aa7; /* json_column_proto_b64 */
    --series-5: #e34948; /* proto_column_proto */
    --series-1-tint: #88b3e7; /* series colors blended 45% toward the surface, for stacked-bar sub-segments */
    --series-2-tint: #80d2b4;
    --series-3-tint: #f4ca71;
    --series-4-tint: #9a91cd;
    --series-5-tint: #ee9a99;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --grid:           #2c2c2a;
      --baseline:       #383835;
      --border:         rgba(255,255,255,0.10);
      --series-1: #3987e5;
      --series-2: #199e70;
      --series-3: #c98500;
      --series-4: #9085e9;
      --series-5: #e66767;
      --series-1-tint: #2b5689;
      --series-2-tint: #196349;
      --series-3-tint: #7a550b;
      --series-4-tint: #5b558b;
      --series-5-tint: #8a4444;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --grid:           #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #199e70;
    --series-3: #c98500;
    --series-4: #9085e9;
    --series-5: #e66767;
    --series-1-tint: #2b5689;
    --series-2-tint: #196349;
    --series-3-tint: #7a550b;
    --series-4-tint: #5b558b;
    --series-5-tint: #8a4444;
  }

  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: var(--page);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    color: var(--text-primary);
  }
  .viz-root { padding: 24px; max-width: 1180px; margin: 0 auto; }

  h1 { font-size: 20px; margin: 0 0 4px; }
  .meta { color: var(--text-secondary); font-size: 13px; margin-bottom: 20px; }
  .meta code { background: var(--grid); padding: 1px 5px; border-radius: 4px; }

  .controls {
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
    padding: 12px 14px; margin-bottom: 12px;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  }
  .control-group { display: flex; align-items: center; gap: 8px; }
  .control-label { font-size: 12px; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }
  select {
    font-family: inherit; font-size: 13px; padding: 6px 10px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
  }
  .spacer { flex: 1 1 auto; }
  .check-label { font-size: 13px; color: var(--text-secondary); display: flex; gap: 6px; align-items: center; cursor: pointer; white-space: nowrap; }
  .dataset-filters { margin-bottom: 18px; }
  #dataset-filters { display: flex; flex-wrap: wrap; gap: 8px 18px; }

  .legend-row { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px 28px; margin-bottom: 16px; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-secondary); }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 10px; height: 10px; border-radius: 2px; flex: none; }
  .fixture-swatch { background: var(--text-secondary); }
  .fixture-swatch.fixture-faded { opacity: 0.55; }
  .stack-swatch.stack-overhead { background: var(--text-muted); }
  .legend[hidden] { display: none; }

  .rows { display: flex; flex-direction: column; gap: 20px; }
  .dataset-title { font-size: 14px; font-weight: 700; margin: 0 0 8px; text-transform: capitalize; }
  .row-charts { display: flex; gap: 14px; }
  @media (max-width: 720px) { .row-charts { flex-direction: column; } }

  .facet {
    flex: 1 1 0; min-width: 0;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 12px 8px;
  }
  .facet h4 {
    font-size: 11.5px; margin: 0 0 8px; font-weight: 600; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: .03em;
  }
  .facet svg { width: 100%; height: auto; display: block; overflow: visible; }
  .placeholder { display: flex; align-items: center; justify-content: center; height: 170px; color: var(--text-muted); font-size: 12.5px; text-align: center; padding: 0 12px; }
  .bar { transition: opacity .1s; }
  .bar.fixture-faded { fill-opacity: 0.55; }
  .bar:hover, .bar.hovered { opacity: 0.82; }
  .bar-label { font-size: 9.5px; fill: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .mult-label { font-size: 8.5px; fill: var(--text-muted); font-variant-numeric: tabular-nums; }
  .axis-line { stroke: var(--baseline); stroke-width: 1; }
  .cat-label { font-size: 9.5px; fill: var(--text-muted); }

  .tooltip {
    position: fixed; pointer-events: none; z-index: 50;
    background: var(--text-primary); color: var(--surface-1);
    font-size: 12px; padding: 6px 9px; border-radius: 6px; line-height: 1.5;
    box-shadow: 0 4px 14px rgba(0,0,0,.18);
    max-width: 260px; opacity: 0; transform: translateY(2px);
    transition: opacity .08s, transform .08s;
  }
  .tooltip.show { opacity: 1; transform: translateY(0); }
  .tooltip .t-value { font-weight: 700; }
  .tooltip .t-key { display: inline-block; width: 9px; height: 2px; margin-right: 5px; vertical-align: middle; }

  .table-wrap { margin-top: 22px; display: none; }
  .table-wrap.show { display: block; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
  th { color: var(--text-muted); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .table-scroll { max-height: 480px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; }

  footer { margin-top: 20px; font-size: 11.5px; color: var(--text-muted); }
</style>
</head>
<body>
<div class="viz-root">
  <h1>Filestream encoding benchmark</h1>
  <div class="meta">__META_LINE__ &middot; __N_ROWS__ benchmark results</div>

  <div class="controls">
    <div class="control-group">
      <span class="control-label">Metric</span>
      <select id="metric-select"></select>
    </div>
    <div class="spacer"></div>
    <label class="check-label"><input type="checkbox" id="table-toggle"> Show raw table</label>
  </div>

  <div class="controls dataset-filters">
    <span class="control-label">Workloads</span>
    <div id="dataset-filters"></div>
  </div>

  <div class="legend-row">
    <div class="legend" id="legend"></div>
    <div class="legend" id="fixture-legend"></div>
    <div class="legend" id="stack-legend" hidden></div>
  </div>

  <div class="rows" id="rows"></div>

  <div class="table-wrap" id="table-wrap">
    <div class="table-scroll">
      <table id="raw-table"><thead></thead><tbody></tbody></table>
    </div>
  </div>

  <footer>Generated from <code>__SOURCE_NAME__</code> by build_dashboard.py.</footer>
</div>
<div class="tooltip" id="tooltip" role="tooltip"></div>

<script>
const ROWS = __ROWS_JSON__;
const DATASETS = __DATASETS_JSON__;
const FORMATS = __FORMATS_JSON__;
const FORMAT_LABELS = __FORMAT_LABELS_JSON__;
const FORMAT_SHORT = __FORMAT_SHORT_JSON__;
const VALUE_MODES = __VALUE_MODES_JSON__;
const FIXTURE_LABELS = { value_json_only: "value-only fixture", typed_only: "typed fixture" };
const OPS = ["Encode", "Decode"];
const SERIES_VARS = ["--series-1","--series-2","--series-3","--series-4","--series-5"];
const SERIES_TINT_VARS = ["--series-1-tint","--series-2-tint","--series-3-tint","--series-4-tint","--series-5-tint"];
const BASELINE_FORMAT = "legacy_json_jsonl";

const METRICS = [
  { key: "ns_per_op",     label: "Latency",              fmt: v => fmtNs(v) },
  { key: "ops_per_sec",   label: "Ops / sec",            fmt: v => fmtOps(v) },
  { key: "mb_per_s",      label: "Throughput",           fmt: v => v.toFixed(1) + " MB/s" },
  { key: "b_per_op",      label: "Memory / op",          fmt: v => fmtBytes(v) },
  { key: "allocs_per_op", label: "Allocations / op",     fmt: v => Math.round(v).toLocaleString() },
  { key: "envelope_bytes",label: "Envelope + Body Bytes",fmt: v => fmtBytes(v), stacked: true },
  { key: "body_bytes",    label: "Body size",            fmt: v => fmtBytes(v) },
  { key: "gzip1_bytes",   label: "Gzip-1 size",          fmt: v => fmtBytes(v) },
  { key: "gzip6_bytes",   label: "Gzip-6 size",          fmt: v => fmtBytes(v) },
];

function fmtNs(v) {
  if (v >= 1e6) return (v/1e6).toFixed(1) + " ms";
  if (v >= 1e3) return (v/1e3).toFixed(1) + " µs";
  return Math.round(v) + " ns";
}
function fmtOps(v) {
  if (v >= 1e6) return (v/1e6).toFixed(1) + "M/s";
  if (v >= 1e3) return (v/1e3).toFixed(1) + "K/s";
  return Math.round(v) + "/s";
}
function fmtBytes(v) {
  if (v >= 1e6) return (v/1e6).toFixed(1) + " MB";
  if (v >= 1e3) return (v/1e3).toFixed(1) + " KB";
  return Math.round(v) + " B";
}
function fmtMult(v) {
  return (v >= 10 ? v.toFixed(1) : v.toFixed(2)) + "×";
}

let state = { metric: "ns_per_op", visible: new Set(DATASETS) };

function getRow(dataset, op, format, valueMode) {
  return ROWS.find(r => r.dataset === dataset && r.op === op && r.format === format && r.value_mode === valueMode);
}

function populateMetricSelect() {
  const sel = document.getElementById("metric-select");
  sel.innerHTML = "";
  METRICS.forEach(m => {
    const o = document.createElement("option");
    o.value = m.key; o.textContent = m.label;
    sel.appendChild(o);
  });
  sel.value = state.metric;
}

function buildDatasetFilters() {
  const el = document.getElementById("dataset-filters");
  el.innerHTML = "";
  DATASETS.forEach(ds => {
    const label = document.createElement("label");
    label.className = "check-label";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.visible.has(ds);
    cb.addEventListener("change", () => {
      if (cb.checked) state.visible.add(ds); else state.visible.delete(ds);
      renderRows();
    });
    const span = document.createElement("span");
    span.textContent = ds.replace(/_/g, " ");
    label.appendChild(cb); label.appendChild(span);
    el.appendChild(label);
  });
}

function buildLegend() {
  const el = document.getElementById("legend");
  el.innerHTML = "";
  FORMATS.forEach((f, i) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    const sw = document.createElement("span");
    sw.className = "legend-swatch";
    sw.style.background = `var(${SERIES_VARS[i]})`;
    const label = document.createElement("span");
    label.textContent = FORMAT_LABELS[f] || f;
    item.appendChild(sw); item.appendChild(label);
    el.appendChild(item);
  });
}

function buildFixtureLegend() {
  const el = document.getElementById("fixture-legend");
  el.innerHTML = "";
  [["typed_only", ""], ["value_json_only", "fixture-faded"]].forEach(([vm, cls]) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    const sw = document.createElement("span");
    sw.className = "legend-swatch fixture-swatch " + cls;
    const label = document.createElement("span");
    label.textContent = FIXTURE_LABELS[vm];
    item.appendChild(sw); item.appendChild(label);
    el.appendChild(item);
  });
}

function buildStackLegend() {
  const el = document.getElementById("stack-legend");
  el.innerHTML = "";
  [["Body bytes", ""], ["Envelope overhead", "stack-overhead"]].forEach(([label, cls]) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    const sw = document.createElement("span");
    sw.className = "legend-swatch stack-swatch " + cls;
    if (!cls) sw.style.background = "var(--text-secondary)";
    const span = document.createElement("span");
    span.textContent = label;
    item.appendChild(sw); item.appendChild(span);
    el.appendChild(item);
  });
}

const tooltip = document.getElementById("tooltip");
function showTooltip(evt, title, valueText, colorVar) {
  tooltip.innerHTML = "";
  const key = document.createElement("span");
  key.className = "t-key";
  key.style.background = `var(${colorVar})`;
  const val = document.createElement("span");
  val.className = "t-value";
  val.textContent = valueText;
  const label = document.createElement("div");
  label.textContent = title;
  tooltip.appendChild(key);
  tooltip.appendChild(val);
  tooltip.appendChild(label);
  tooltip.classList.add("show");
  moveTooltip(evt);
}
function moveTooltip(evt) {
  const pad = 14;
  tooltip.style.left = (evt.clientX + pad) + "px";
  tooltip.style.top = (evt.clientY + pad) + "px";
}
function hideTooltip() { tooltip.classList.remove("show"); }

function buildBarSVG(dataset, op, metric) {
  const W = 560, H = 230;
  const padTop = 32, padBottom = 30, padLeft = 10, padRight = 10;
  const groupGap = 16, barGap = 30, barW = 22;
  const plotW = W - padLeft - padRight;
  const plotH = H - padTop - padBottom;
  const groupW = (plotW - groupGap * (FORMATS.length - 1)) / FORMATS.length;

  const allVals = [];
  FORMATS.forEach(f => VALUE_MODES.forEach(vm => {
    const row = getRow(dataset, op, f, vm);
    if (row && row[metric.key] != null) allVals.push(row[metric.key]);
  }));
  const maxV = Math.max(...allVals, 0.0001);

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const baseline = document.createElementNS(svgNS, "line");
  baseline.setAttribute("class", "axis-line");
  baseline.setAttribute("x1", padLeft); baseline.setAttribute("x2", W - padRight);
  baseline.setAttribute("y1", padTop + plotH); baseline.setAttribute("y2", padTop + plotH);
  svg.appendChild(baseline);

  FORMATS.forEach((f, gi) => {
    const groupX = padLeft + gi * (groupW + groupGap);
    const pairW = barW * 2 + barGap;
    const pairX = groupX + (groupW - pairW) / 2;

    const baselineByMode = {};
    VALUE_MODES.forEach(vm => {
      const br = getRow(dataset, op, BASELINE_FORMAT, vm);
      baselineByMode[vm] = br ? br[metric.key] : null;
    });

    VALUE_MODES.forEach((vm, vi) => {
      const row = getRow(dataset, op, f, vm);
      const x = pairX + vi * (barW + barGap);
      if (!row || row[metric.key] == null) return;
      const v = row[metric.key];
      const fadedCls = vm === "value_json_only" ? " fixture-faded" : "";
      const barH = Math.max(1.5, (v / maxV) * (plotH - 4));
      const y = padTop + plotH - barH;
      const baselineV = baselineByMode[vm];
      const mult = baselineV ? v / baselineV : null;

      const addRect = (segY, segH, fillVar, tooltipFn) => {
        const rect = document.createElementNS(svgNS, "rect");
        rect.setAttribute("class", "bar" + fadedCls);
        rect.setAttribute("x", x); rect.setAttribute("y", segY);
        rect.setAttribute("width", barW); rect.setAttribute("height", Math.max(0, segH));
        rect.setAttribute("rx", 3);
        rect.setAttribute("fill", `var(${fillVar})`);
        rect.addEventListener("pointermove", evt => tooltipFn(evt));
        rect.addEventListener("pointerleave", hideTooltip);
        svg.appendChild(rect);
      };

      if (metric.stacked && row.body_bytes != null) {
        const bodyV = Math.min(row.body_bytes, v);
        const overheadV = v - bodyV;
        const bodyH = (bodyV / v) * barH;
        const overheadH = barH - bodyH;
        const gap = bodyH > 0 && overheadH > 0 ? 2 : 0;
        const bodyY = padTop + plotH - bodyH;
        const overheadH2 = Math.max(0, overheadH - gap);
        const overheadY = bodyY - gap - overheadH2;

        addRect(bodyY, bodyH, SERIES_VARS[gi], evt => {
          const title = `${FORMAT_LABELS[f] || f} — ${FIXTURE_LABELS[vm]} · body`;
          showTooltip(evt, title, fmtBytes(bodyV), SERIES_VARS[gi]);
        });
        if (overheadH2 > 0) {
          addRect(overheadY, overheadH2, SERIES_TINT_VARS[gi], evt => {
            const title = `${FORMAT_LABELS[f] || f} — ${FIXTURE_LABELS[vm]} · envelope overhead`;
            showTooltip(evt, title, fmtBytes(overheadV), SERIES_TINT_VARS[gi]);
          });
        }
      } else {
        addRect(y, barH, SERIES_VARS[gi], evt => {
          const title = `${FORMAT_LABELS[f] || f} — ${FIXTURE_LABELS[vm]}`;
          const valueText = mult != null ? `${metric.fmt(v)} · ${fmtMult(mult)}` : metric.fmt(v);
          showTooltip(evt, title, valueText, SERIES_VARS[gi]);
        });
      }

      const valueLabel = document.createElementNS(svgNS, "text");
      valueLabel.setAttribute("class", "bar-label");
      valueLabel.setAttribute("x", x + barW / 2);
      valueLabel.setAttribute("y", Math.max(11, y - 15));
      valueLabel.setAttribute("text-anchor", "middle");
      valueLabel.textContent = metric.fmt(v);
      svg.appendChild(valueLabel);

      const multLabel = document.createElementNS(svgNS, "text");
      multLabel.setAttribute("class", "mult-label");
      multLabel.setAttribute("x", x + barW / 2);
      multLabel.setAttribute("y", Math.max(23, y - 4));
      multLabel.setAttribute("text-anchor", "middle");
      multLabel.textContent = mult != null ? fmtMult(mult) : "—";
      svg.appendChild(multLabel);
    });

    const catLabel = document.createElementNS(svgNS, "text");
    catLabel.setAttribute("class", "cat-label");
    catLabel.setAttribute("x", groupX + groupW / 2);
    catLabel.setAttribute("y", padTop + plotH + 18);
    catLabel.setAttribute("text-anchor", "middle");
    catLabel.textContent = FORMAT_SHORT[f] || f;
    svg.appendChild(catLabel);
  });

  return svg;
}

function buildFacetContent(dataset, op, metric) {
  const anyValue = FORMATS.some(f => VALUE_MODES.some(vm => {
    const row = getRow(dataset, op, f, vm);
    return row && row[metric.key] != null;
  }));
  if (!anyValue) {
    const div = document.createElement("div");
    div.className = "placeholder";
    div.textContent = `${metric.label} not recorded for ${op}`;
    return div;
  }
  return buildBarSVG(dataset, op, metric);
}

function renderRows() {
  const container = document.getElementById("rows");
  container.innerHTML = "";
  const metric = METRICS.find(m => m.key === state.metric);
  DATASETS.filter(ds => state.visible.has(ds)).forEach(dataset => {
    const rowEl = document.createElement("div");
    rowEl.className = "dataset-row";
    const h3 = document.createElement("h3");
    h3.className = "dataset-title";
    h3.textContent = dataset.replace(/_/g, " ");
    rowEl.appendChild(h3);

    const chartsEl = document.createElement("div");
    chartsEl.className = "row-charts";
    OPS.forEach(op => {
      const facet = document.createElement("div");
      facet.className = "facet";
      const h4 = document.createElement("h4");
      h4.textContent = op;
      facet.appendChild(h4);
      facet.appendChild(buildFacetContent(dataset, op, metric));
      chartsEl.appendChild(facet);
    });
    rowEl.appendChild(chartsEl);
    container.appendChild(rowEl);
  });
}

function renderTable() {
  const cols = ["benchmark","op","dataset","value_mode","format","iterations",
    "ns_per_op","ops_per_sec","mb_per_s","b_per_op","allocs_per_op","body_bytes","envelope_bytes",
    "gzip1_bytes","gzip1_ratio","gzip6_bytes","gzip6_ratio","envelope_ratio","rows_per_op","cells_per_op"];
  const table = document.getElementById("raw-table");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = ""; tbody.innerHTML = "";
  const trh = document.createElement("tr");
  cols.forEach(c => {
    const th = document.createElement("th");
    th.textContent = c;
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  ROWS.forEach(r => {
    const tr = document.createElement("tr");
    cols.forEach(c => {
      const td = document.createElement("td");
      const v = r[c];
      td.textContent = (v === null || v === undefined) ? "" : v;
      if (typeof v === "number") td.classList.add("num");
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function updateStackLegendVisibility() {
  const metric = METRICS.find(m => m.key === state.metric);
  document.getElementById("stack-legend").hidden = !metric.stacked;
}

document.getElementById("metric-select").addEventListener("change", e => {
  state.metric = e.target.value;
  updateStackLegendVisibility();
  renderRows();
});
document.getElementById("table-toggle").addEventListener("change", e => {
  document.getElementById("table-wrap").classList.toggle("show", e.target.checked);
});
window.addEventListener("pointermove", moveTooltip);

populateMetricSelect();
buildDatasetFilters();
buildLegend();
buildFixtureLegend();
buildStackLegend();
updateStackLegendVisibility();
renderTable();
renderRows();
</script>
</body>
</html>
"""

FORMAT_LABELS = {
    "legacy_json_jsonl": "legacy JSON (JSONL)",
    "json_row_proto_b64": "row proto, base64-in-JSON",
    "proto_row_proto": "row proto, native envelope",
    "json_column_proto_b64": "column proto, base64-in-JSON",
    "proto_column_proto": "column proto, native envelope",
}

FORMAT_SHORT = {
    "legacy_json_jsonl": "legacy JSON",
    "json_row_proto_b64": "row · b64",
    "proto_row_proto": "row · native",
    "json_column_proto_b64": "col · b64",
    "proto_column_proto": "col · native",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csvfile")
    ap.add_argument("-o", "--html", default="bench_dashboard.html", help="output HTML path")
    args = ap.parse_args()

    rows = load_rows(args.csvfile)
    if not rows:
        sys.exit(f"no rows in {args.csvfile}")

    datasets = ordered_uniques(rows, "dataset", DATASET_ORDER)
    formats = ordered_uniques(rows, "format", FORMAT_ORDER)
    value_modes = ordered_uniques(rows, "value_mode", VALUE_MODE_ORDER)

    html = (PAGE_TEMPLATE
            .replace("__ROWS_JSON__", json.dumps(rows))
            .replace("__DATASETS_JSON__", json.dumps(datasets))
            .replace("__FORMATS_JSON__", json.dumps(formats))
            .replace("__FORMAT_LABELS_JSON__", json.dumps(FORMAT_LABELS))
            .replace("__FORMAT_SHORT_JSON__", json.dumps(FORMAT_SHORT))
            .replace("__VALUE_MODES_JSON__", json.dumps(value_modes))
            .replace("__N_ROWS__", str(len(rows)))
            .replace("__SOURCE_NAME__", args.csvfile)
            .replace("__META_LINE__", "Apple M5 Pro &middot; darwin/arm64"))

    with open(args.html, "w") as f:
        f.write(html)
    print(f"wrote {args.html}", file=sys.stderr)


if __name__ == "__main__":
    main()
