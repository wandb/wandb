"""Build a self-contained HTML dashboard from a parsed benchmark CSV.

    python3 parse_bench.py bench-run.log             # writes bench-run.csv
    python3 build_dashboard.py bench-run.csv         # writes bench-run-dash.html

No external JS/CSS dependencies: the page is plain HTML/CSS/SVG so it opens
directly from disk (file://) with no server or CDN needed.

The CSV uses the split format components produced by parse_bench.py:
payload_format (jsonl, row_proto, column_proto), envelope_format (json,
native), and value_mode (json_value, typed_value). The chart nests bars by
GROUP_ORDER (see the JS constant) and offers per-variant checkboxes.
"""
import argparse
import csv
import json
import os
import sys

FLOAT_FIELDS = [
    "iterations", "allocs_per_op", "b_per_op", "body_bytes", "cells_per_op",
    "envelope_bytes", "envelope_ratio", "gzip1_bytes", "gzip1_ratio",
    "gzip6_bytes", "gzip6_ratio", "mb_per_s", "ns_per_op", "ops_per_sec", "rows_per_op",
]

DATASET_ORDER = ["tiny", "dense_numeric", "sparse_mixed", "wide_mixed", "nested_json", "system_metrics"]


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
    --series-1: #2a78d6; /* payload: jsonl */
    --series-2: #1baf7a; /* payload: row_proto */
    --series-3: #eda100;
    --series-4: #4a3aa7; /* payload: column_proto */
    --series-5: #e34948;
    --series-1-tint: #88b3e7; /* series colors blended 45% toward the surface; tint = json envelope */
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
  .filters-panel { margin-bottom: 12px; align-items: flex-start; }
  #dataset-filters { display: flex; flex-wrap: wrap; gap: 8px 18px; }
  .variant-groups { display: flex; flex-wrap: wrap; gap: 8px 26px; }
  .variant-group { display: flex; align-items: center; gap: 10px; }
  .variant-group .group-name { font-size: 12px; color: var(--text-muted); font-weight: 600; }

  .legend-row { display: flex; flex-wrap: wrap; gap: 8px 28px; margin-bottom: 16px; }
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
  .cat-label { font-size: 9px; fill: var(--text-muted); }

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

  <div class="controls filters-panel">
    <span class="control-label">Workloads</span>
    <div id="dataset-filters"></div>
  </div>

  <div class="controls filters-panel">
    <span class="control-label">Variants</span>
    <div class="variant-groups" id="variant-filters"></div>
  </div>

  <div class="legend-row">
    <div class="legend" id="payload-legend"></div>
    <div class="legend" id="envelope-legend"></div>
    <div class="legend" id="value-mode-legend"></div>
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
const OPS = ["Encode", "Decode"];

// The three independent format components. `order` fixes display/sort order;
// `short` is the abbreviation used in the tiered axis labels.
const COMPONENTS = [
  { key: "envelope_format", label: "Envelope", order: ["json", "native"],
    short: { json: "json", native: "native" } },
  { key: "payload_format",  label: "Payload",  order: ["jsonl", "row_proto", "column_proto"],
    short: { jsonl: "jsonl", row_proto: "row", column_proto: "col" } },
  { key: "value_mode",      label: "Value mode", order: ["json_value", "typed_value"],
    short: { json_value: "jv", typed_value: "tv" } },
];
const COMPONENT_BY_KEY = Object.fromEntries(COMPONENTS.map(c => [c.key, c]));

// Nesting order for chart grouping, outermost first. Edit to regroup.
const GROUP_ORDER = ["envelope_format", "payload_format", "value_mode"];

// Hue follows the payload; tint of the same hue = json envelope.
const SERIES_VARS = ["--series-1","--series-2","--series-3","--series-4","--series-5"];
const SERIES_TINT_VARS = ["--series-1-tint","--series-2-tint","--series-3-tint","--series-4-tint","--series-5-tint"];
const PAYLOAD_SERIES_INDEX = { jsonl: 0, row_proto: 1, column_proto: 3 };

// Multiplier baseline: the legacy transport, matched on value_mode.
const BASELINE = { payload_format: "jsonl", envelope_format: "json" };

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

// Combos that actually exist in the data (not every cross-product is valid,
// e.g. jsonl only ships in a json envelope).
const EXISTING_COMBOS = (() => {
  const seen = new Set();
  const combos = [];
  ROWS.forEach(r => {
    const key = COMPONENTS.map(c => r[c.key]).join("|");
    if (!seen.has(key)) {
      seen.add(key);
      combos.push(Object.fromEntries(COMPONENTS.map(c => [c.key, r[c.key]])));
    }
  });
  return combos;
})();

let state = {
  metric: "ns_per_op",
  visible: new Set(DATASETS),
  variants: Object.fromEntries(COMPONENTS.map(c => [c.key, new Set(c.order)])),
};

function selectedLeaves() {
  const leaves = EXISTING_COMBOS.filter(combo =>
    COMPONENTS.every(c => state.variants[c.key].has(combo[c.key]))
  );
  leaves.sort((a, b) => {
    for (const key of GROUP_ORDER) {
      const order = COMPONENT_BY_KEY[key].order;
      const d = order.indexOf(a[key]) - order.indexOf(b[key]);
      if (d) return d;
    }
    return 0;
  });
  return leaves;
}

function getRow(dataset, op, leaf) {
  return ROWS.find(r =>
    r.dataset === dataset && r.op === op &&
    COMPONENTS.every(c => r[c.key] === leaf[c.key])
  );
}

function getBaselineRow(dataset, op, valueMode) {
  return getRow(dataset, op, {
    payload_format: BASELINE.payload_format,
    envelope_format: BASELINE.envelope_format,
    value_mode: valueMode,
  });
}

function leafFill(leaf) {
  const i = PAYLOAD_SERIES_INDEX[leaf.payload_format] ?? 4;
  return leaf.envelope_format === "native" ? SERIES_VARS[i] : SERIES_TINT_VARS[i];
}

function leafClasses(leaf) {
  return "bar" + (leaf.value_mode === "json_value" ? " fixture-faded" : "");
}

function leafTitle(leaf) {
  return `${leaf.payload_format} / ${leaf.envelope_format} — ${leaf.value_mode}`;
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

function buildVariantFilters() {
  const el = document.getElementById("variant-filters");
  el.innerHTML = "";
  COMPONENTS.forEach(c => {
    const group = document.createElement("div");
    group.className = "variant-group";
    const name = document.createElement("span");
    name.className = "group-name";
    name.textContent = c.label + ":";
    group.appendChild(name);
    c.order.forEach(variant => {
      const label = document.createElement("label");
      label.className = "check-label";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.variants[c.key].has(variant);
      cb.addEventListener("change", () => {
        if (cb.checked) state.variants[c.key].add(variant);
        else state.variants[c.key].delete(variant);
        renderRows();
      });
      const span = document.createElement("span");
      span.textContent = variant;
      label.appendChild(cb); label.appendChild(span);
      group.appendChild(label);
    });
    el.appendChild(group);
  });
}

function makeLegendItem(el, swatchStyler, text) {
  const item = document.createElement("div");
  item.className = "legend-item";
  const sw = document.createElement("span");
  sw.className = "legend-swatch";
  swatchStyler(sw);
  const label = document.createElement("span");
  label.textContent = text;
  item.appendChild(sw); item.appendChild(label);
  el.appendChild(item);
}

function buildLegends() {
  const payloadEl = document.getElementById("payload-legend");
  payloadEl.innerHTML = "";
  COMPONENT_BY_KEY.payload_format.order.forEach(p => {
    const i = PAYLOAD_SERIES_INDEX[p] ?? 4;
    makeLegendItem(payloadEl, sw => { sw.style.background = `var(${SERIES_VARS[i]})`; }, p);
  });

  const envelopeEl = document.getElementById("envelope-legend");
  envelopeEl.innerHTML = "";
  makeLegendItem(envelopeEl, sw => { sw.style.background = "var(--series-1)"; }, "native envelope (solid)");
  makeLegendItem(envelopeEl, sw => { sw.style.background = "var(--series-1-tint)"; }, "json envelope (tint)");

  const vmEl = document.getElementById("value-mode-legend");
  vmEl.innerHTML = "";
  makeLegendItem(vmEl, sw => { sw.classList.add("fixture-swatch"); }, "typed_value");
  makeLegendItem(vmEl, sw => { sw.classList.add("fixture-swatch", "fixture-faded"); }, "json_value");

  const stackEl = document.getElementById("stack-legend");
  stackEl.innerHTML = "";
  makeLegendItem(stackEl, sw => { sw.style.background = "var(--text-secondary)"; }, "Body bytes");
  makeLegendItem(stackEl, sw => { sw.classList.add("stack-swatch", "stack-overhead"); }, "Envelope overhead");
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

// Gap (px) between adjacent bars, by the outermost nesting level at which
// they differ: [outer, middle, inner].
const LEVEL_GAPS = [32, 20, 10];

function diffLevel(a, b) {
  for (let i = 0; i < GROUP_ORDER.length; i++) {
    if (a[GROUP_ORDER[i]] !== b[GROUP_ORDER[i]]) return i;
  }
  return GROUP_ORDER.length - 1;
}

function buildBarSVG(dataset, op, metric, leaves) {
  const W = 620, H = 252;
  const padTop = 32, padBottom = 46, padLeft = 10, padRight = 10;
  const plotW = W - padLeft - padRight;
  const plotH = H - padTop - padBottom;
  const axisY = padTop + plotH;

  // Horizontal layout: fixed-width bars, level-dependent gaps, centered.
  const gaps = leaves.slice(1).map((leaf, i) => LEVEL_GAPS[diffLevel(leaves[i], leaf)]);
  const totalGaps = gaps.reduce((a, b) => a + b, 0);
  const barW = Math.min(24, Math.max(8, (plotW - totalGaps) / Math.max(1, leaves.length)));
  const usedW = leaves.length * barW + totalGaps;
  const xs = [];
  let x = padLeft + Math.max(0, (plotW - usedW) / 2);
  leaves.forEach((leaf, i) => {
    if (i > 0) x += barW + gaps[i - 1];
    xs.push(x);
  });

  const allVals = [];
  leaves.forEach(leaf => {
    const row = getRow(dataset, op, leaf);
    if (row && row[metric.key] != null) allVals.push(row[metric.key]);
  });
  const maxV = Math.max(...allVals, 0.0001);

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const baseline = document.createElementNS(svgNS, "line");
  baseline.setAttribute("class", "axis-line");
  baseline.setAttribute("x1", padLeft); baseline.setAttribute("x2", W - padRight);
  baseline.setAttribute("y1", axisY); baseline.setAttribute("y2", axisY);
  svg.appendChild(baseline);

  // Bars + labels. Value labels get a simple greedy collision nudge.
  let prevLabel = null;
  leaves.forEach((leaf, i) => {
    const row = getRow(dataset, op, leaf);
    if (!row || row[metric.key] == null) return;
    const v = row[metric.key];
    const barX = xs[i];
    const barH = Math.max(1.5, (v / maxV) * (plotH - 4));
    const barY = axisY - barH;
    const baselineRow = getBaselineRow(dataset, op, leaf.value_mode);
    const baselineV = baselineRow ? baselineRow[metric.key] : null;
    const mult = baselineV ? v / baselineV : null;
    const fillVar = leafFill(leaf);
    const cls = leafClasses(leaf);

    const addRect = (segY, segH, segFill, tooltipFn) => {
      const rect = document.createElementNS(svgNS, "rect");
      rect.setAttribute("class", cls);
      rect.setAttribute("x", barX); rect.setAttribute("y", segY);
      rect.setAttribute("width", barW); rect.setAttribute("height", Math.max(0, segH));
      rect.setAttribute("rx", 3);
      rect.setAttribute("fill", `var(${segFill})`);
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
      const bodyY = axisY - bodyH;
      const overheadH2 = Math.max(0, overheadH - gap);
      const overheadY = bodyY - gap - overheadH2;
      addRect(bodyY, bodyH, fillVar, evt => {
        showTooltip(evt, leafTitle(leaf) + " · body", fmtBytes(bodyV), fillVar);
      });
      if (overheadH2 > 0) {
        addRect(overheadY, overheadH2, "--text-muted", evt => {
          showTooltip(evt, leafTitle(leaf) + " · envelope overhead", fmtBytes(overheadV), "--text-muted");
        });
      }
    } else {
      addRect(barY, barH, fillVar, evt => {
        const valueText = mult != null ? `${metric.fmt(v)} · ${fmtMult(mult)}` : metric.fmt(v);
        showTooltip(evt, leafTitle(leaf), valueText, fillVar);
      });
    }

    const valueText = metric.fmt(v);
    const labelW = valueText.length * 5.3;
    let valueY = Math.max(11, barY - 15);
    // Nudge up if this label would collide with the previous bar's label.
    if (prevLabel &&
        barX + barW / 2 - labelW / 2 < prevLabel.right + 3 &&
        Math.abs(valueY - prevLabel.y) < 11) {
      valueY = Math.max(11, prevLabel.y - 12);
    }
    prevLabel = { right: barX + barW / 2 + labelW / 2, y: valueY };

    const valueLabel = document.createElementNS(svgNS, "text");
    valueLabel.setAttribute("class", "bar-label");
    valueLabel.setAttribute("x", barX + barW / 2);
    valueLabel.setAttribute("y", valueY);
    valueLabel.setAttribute("text-anchor", "middle");
    valueLabel.textContent = valueText;
    svg.appendChild(valueLabel);

    const multLabel = document.createElementNS(svgNS, "text");
    multLabel.setAttribute("class", "mult-label");
    multLabel.setAttribute("x", barX + barW / 2);
    multLabel.setAttribute("y", valueY + 11);
    multLabel.setAttribute("text-anchor", "middle");
    multLabel.textContent = mult != null ? fmtMult(mult) : "—";
    svg.appendChild(multLabel);
  });

  // Tiered category labels: innermost grouping level closest to the axis,
  // outermost at the bottom; each label spans its run of equal values.
  const nLevels = GROUP_ORDER.length;
  for (let level = 0; level < nLevels; level++) {
    const compo = COMPONENT_BY_KEY[GROUP_ORDER[level]];
    const tierY = axisY + 12 + (nLevels - 1 - level) * 11;
    let runStart = 0;
    for (let i = 1; i <= leaves.length; i++) {
      const runEnded = i === leaves.length ||
        GROUP_ORDER.slice(0, level + 1).some(k => leaves[i][k] !== leaves[runStart][k]);
      if (!runEnded) continue;
      const x0 = xs[runStart], x1 = xs[i - 1] + barW;
      const text = compo.short[leaves[runStart][compo.key]] ?? leaves[runStart][compo.key];
      // Skip labels that would overflow their run (identity still available
      // via color/opacity, the legend, and tooltips).
      if (text.length * 5 <= x1 - x0 + 8) {
        const label = document.createElementNS(svgNS, "text");
        label.setAttribute("class", "cat-label");
        label.setAttribute("x", (x0 + x1) / 2);
        label.setAttribute("y", tierY);
        label.setAttribute("text-anchor", "middle");
        label.textContent = text;
        svg.appendChild(label);
      }
      runStart = i;
    }
  }

  return svg;
}

function buildFacetContent(dataset, op, metric, leaves) {
  if (!leaves.length) {
    const div = document.createElement("div");
    div.className = "placeholder";
    div.textContent = "no variants selected";
    return div;
  }
  const anyValue = leaves.some(leaf => {
    const row = getRow(dataset, op, leaf);
    return row && row[metric.key] != null;
  });
  if (!anyValue) {
    const div = document.createElement("div");
    div.className = "placeholder";
    div.textContent = `${metric.label} not recorded for ${op}`;
    return div;
  }
  return buildBarSVG(dataset, op, metric, leaves);
}

function renderRows() {
  const container = document.getElementById("rows");
  container.innerHTML = "";
  const metric = METRICS.find(m => m.key === state.metric);
  const leaves = selectedLeaves();
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
      facet.appendChild(buildFacetContent(dataset, op, metric, leaves));
      chartsEl.appendChild(facet);
    });
    rowEl.appendChild(chartsEl);
    container.appendChild(rowEl);
  });
}

function renderTable() {
  const cols = ["benchmark","op","dataset","value_mode","payload_format","envelope_format","iterations",
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
buildVariantFilters();
buildLegends();
updateStackLegendVisibility();
renderTable();
renderRows();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csvfile")
    ap.add_argument("-o", "--html", default=None,
                    help="output HTML path (default: <csvfile minus extension>-dash.html)")
    args = ap.parse_args()

    rows = load_rows(args.csvfile)
    if not rows:
        sys.exit(f"no rows in {args.csvfile}")
    if "payload_format" not in rows[0]:
        sys.exit(f"{args.csvfile} has no payload_format column; re-run parse_bench.py to regenerate it")

    datasets = ordered_uniques(rows, "dataset", DATASET_ORDER)
    out_path = args.html or os.path.splitext(args.csvfile)[0] + "-dash.html"

    html = (PAGE_TEMPLATE
            .replace("__ROWS_JSON__", json.dumps(rows))
            .replace("__DATASETS_JSON__", json.dumps(datasets))
            .replace("__N_ROWS__", str(len(rows)))
            .replace("__SOURCE_NAME__", args.csvfile)
            .replace("__META_LINE__", "Apple M5 Pro &middot; darwin/arm64"))

    with open(out_path, "w") as f:
        f.write(html)
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
