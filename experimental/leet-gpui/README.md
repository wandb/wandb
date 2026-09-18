# leet-gpui

W&B LEET as a native GPU app. Same wandb directory, same runs, same keyboard model as the terminal LEET, but charts are drawn as vector paths with hover readouts, smoothing, and log scales, closer to the W&B workspace page than to a terminal grid.

This is an experiment. It lives next to the Python and Go code but is not wired into the `wandb` CLI or the wheel yet.

## Run it

```bash
cd experimental/leet-gpui
cargo run --release -p leet-gpui -- ~/path/to/wandb
```

The argument follows `wandb leet`: a wandb directory opens the workspace with the latest run selected, a run directory or `.wandb` file opens that run. Press `?` for the key list.

macOS builds compile the Metal shaders at runtime (`runtime_shaders`), so Xcode is not required; the command line tools are enough. Linux uses the Vulkan backend via blade, which is gpui's default.

## Layout

```
crates/
  leet-proto   prost bindings for wandb_internal.proto (committed, no protoc needed)
  leet-wire    transaction log reader: LevelDB-style records, CRC, live tailing
  leet-data    HistorySource trait and the .wandb implementation
  leet-plot    chart geometry: scales, ticks, decimation, smoothing (no GUI dependency)
  leet-gpui    the app: workspace entity, run readers, chart canvas, keymap
```

`leet-proto`, `leet-wire`, and the `leet-data` modules are taken unchanged from the leet Rust port (worktree branch `worktree-leet-rs`), where they were verified record by record against the Go implementation. `leet-plot` and `leet-gpui` are new. See `docs/PORTING.md` for how the Go LEET maps onto this code.

## Charts

No plotting library. Each chart is a `canvas` element that paints with gpui's `PathBuilder`: one stroked polyline per run, tick labels shaped through the window's text system, and a crosshair from `window.mouse_position()`. Series are reduced to two points per pixel column (the column's minimum and maximum) before tessellation, so a run with a million steps costs the same to draw as one with a thousand.

The libraries considered and rejected: kuva renders SVG/PNG/PDF files, plotlars wraps plotly.js or plotters into HTML or images, charming drives Apache ECharts through JavaScript. None of them can paint into a gpui window. `plotters-gpui` and `gpui-component`'s charts do, but both target dashboards with tens of points and neither decimates; the plot code needed here is a few hundred lines and owns the hot path.

## Web

gpui's web platform (wasm32-unknown-unknown, WebGPU with a WebGL2 fallback) merged into Zed in February 2026 but has not shipped on crates.io; it lives in the unpublished `gpui_web` and `gpui_platform` crates. When it does, the app crate needs a second data source (HTTP against wandb-core's local run API or the W&B GraphQL and parquet endpoints) since a browser cannot tail a `.wandb` file; everything above `source.rs` is free of threads and file IO for that reason.
