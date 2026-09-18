# leet-gpui

W&B LEET as a native GPU app. Same wandb directory, same runs, same keyboard model and pane layout as the terminal LEET, but charts are drawn as vector paths with hover readouts, smoothing, and log scales, closer to the W&B workspace page than to a terminal grid.

This is an experiment. It lives next to the Python and Go code but is not wired into the `wandb` CLI or the wheel yet.

## Run it

```bash
cd experimental/leet-gpui
cargo run --release -p leet-gpui -- ~/path/to/wandb
```

The argument follows `wandb leet`: a wandb directory opens the workspace, a run directory or `.wandb` file opens that run. Press `?` for the key list.

macOS builds compile the Metal shaders at runtime (`runtime_shaders`), so Xcode is not required; the command line tools are enough. Linux uses gpui's default Vulkan backend.

## What it shows

The layout is leet's workspace: a runs sidebar on the left, a central column with the metrics grid over a lower tier of system metrics and console logs, the run overview on the right, and a status bar. `1`, `2`, `4`, `[`, `]` toggle panes, `tab` cycles focus, `n`/`N` page a grid, `space` selects runs to chart, `p` pins the run the overview, system, and console panes follow. Pane borders drag; `0` resets them. Panes slide in and out over 150 ms on leet's ease-out cubic curve. `c` or `r` followed by a digit sets the focused grid's columns or rows. Grids show fewer rows when their pane is short rather than charts without axes.

Hovering a chart shows every series' value at that x, and the crosshair is linked across charts of the same axis so the same step can be read off all of them; `i` unlinks it. The mouse wheel zooms the x axis of the chart under it around the pointer, the y axis follows the visible window, and `z` resets the focused chart.

Two files persist state, both in leet's format. `~/.config/wandb/wandb-leet-gpui.json` (or under `WANDB_CONFIG_DIR`) holds pane visibility, grid sizes, layout fractions, and smoothing. `.wandb-leet.json` inside the wandb directory is the file the terminal LEET writes: filters, selected and pinned runs, and the newest run at the time of saving, so a new run since the last visit is selected on open. Both apps read and write the same keys and leave each other's alone.

## Layout

```
crates/
  leet-proto   prost bindings for wandb_internal.proto (committed, no protoc needed)
  leet-wire    transaction log reader: LevelDB-style records, CRC, live tailing
  leet-ingest  decodes records into per-metric columns, console lines, and run metadata
  leet-data    run overview trees and the system metric definitions from the leet Rust port
  leet-plot    chart geometry: scales, ticks, decimation, smoothing (no GUI dependency)
  leet-gpui    the app: workspace entity, panes, chart canvas, keymap, config
```

`leet-proto`, `leet-wire`, and `leet-data` are taken unchanged from the leet Rust port (worktree branch `worktree-leet-rs`), where they were verified against the Go implementation. `leet-ingest`, `leet-plot`, and `leet-gpui` are new. See `docs/PORTING.md` for how the Go LEET maps onto this code.

## Performance

A run that already exists on disk is loaded by every core. `leet-ingest` splits the file into block-aligned ranges (a few small ones first so the first batch lands within milliseconds), frames and decodes each range on a worker, and hands the ranges to the consumer in file order as batches of packed per-metric columns. Hot record types are read with a small protobuf wire walker rather than prost, so history items cost a byte compare against the previous record's key at the same position and a float parse, with no string allocation. Summary records, which a wide run writes at every step, are folded to the latest value per key as bytes and reach the consumer once. Batch buffers go back to a pool after use because freeing a buffer another thread filled costs milliseconds on macOS. After the file has been read once, a single thread follows its tail.

In the app each batch is appended to per-series columns that keep a running extent, an incrementally extended smoothed copy, and the last decimated polyline keyed by length, smoothing, x range, and pixel width. All loading runs share one frame budget: batches are applied for 6 ms after a frame starts and the next batch waits for the next frame, so a large load stays visible as it comes in. The lists a frame derives from the data (metric names, system chart groups, overview rows) are rebuilt only when their inputs change.

Measured on an M4 Max with `cargo run --release -p leet-ingest --example bench -- run.wandb`:

| File | Decode | In the app |
|---|---|---|
| 300 MB, 5000 metrics, 5 M points | 0.073 s, 4.1 GB/s | first batch drawn 80 ms after selecting the run, all of it within 0.2 s |
| 6.7 MB, 62 metrics, 57 k points | 0.008 s | immediate |

The first version of the pipeline decoded with prost into one message per record and took 1.5 s for the same file; the sequential single-thread walker takes 0.95 s.

## Charts

No plotting library. Each chart is a `canvas` element that paints with gpui's `PathBuilder`: one stroked polyline per series, tick labels shaped through the window's text system, and a crosshair from `window.mouse_position()`. Series are reduced to two points per pixel column (the column's minimum and maximum) before tessellation, so a run with a million steps costs the same to draw as one with a thousand. System charts share the code with a time axis and the fixed ranges leet's metric table prescribes for percentages.

The libraries considered and rejected: kuva renders SVG/PNG/PDF files, plotlars wraps plotly.js or plotters into HTML or images, charming drives Apache ECharts through JavaScript. None of them can paint into a gpui window. `plotters-gpui` and `gpui-component`'s charts do, but both target dashboards with tens of points and neither decimates; the plot code needed here is a few hundred lines and owns the hot path.

## Web

gpui's web platform (wasm32-unknown-unknown, WebGPU with a WebGL2 fallback) merged into Zed in February 2026 but has not shipped on crates.io; it lives in the unpublished `gpui_web` and `gpui_platform` crates. When it does, the app crate needs a second data source (HTTP against wandb-core's local run API or the W&B GraphQL and parquet endpoints) since a browser cannot tail a `.wandb` file; everything above `source.rs` is free of threads and file IO for that reason.
