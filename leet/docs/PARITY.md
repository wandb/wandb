# LEET Go→Rust Parity Checklist (Definition of Done)

Source of truth: `core/internal/leet` (Go), `wandb/cli/leet.py`, and `core/cmd/wandb-core/main.go`
(`leetMain`, `runLeetCommand`) at this worktree revision. This is a living tracker: each port PR
flips `Status` cells (`pending` → `done`, or `n/a` + note). Feature rows reference stable scenario
IDs used by the differential harness.

Verification layers:

| Layer | Meaning |
|---|---|
| `pty` | Full-app differential scenario: Go and Rust binaries driven identically under a PTY, frames diffed |
| `unit-diff` | Sub-PTY differential: canvas dump / go_fmt / width / record-stream comparison against Go output |
| `proto` | Protocol test on emitted escape sequences (Kitty APC, OSC 11, SGR mouse, alt-screen) |
| `live` | Manual/live smoke against real terminals or real W&B backend, non-diffed |

## 1. CLI contract

### 1.1 `wandb leet` Python wrapper (wandb/cli/leet.py) — unchanged, but defines the argv the Rust binary must accept

- Click group `DefaultCommandGroup`, default subcommand `run`: `wandb leet [PATH]` ≡ `wandb leet run [PATH]`; unknown first arg or leading `-` falls through to `run`. Help flags `-h`/`--help`.
- Subcommands: `run` (optional `PATH`, hidden `--pprof ADDR`), `symon` (hidden `--pprof`, `--interval DURATION`), `config`.
- PATH resolution (`_resolve_path`): none → `settings.wandb_dir` (workspace); `*.wandb` file → wandb_dir = parent's parent + `--run-file`; dir containing exactly one `run-*.wandb` → wandb_dir = parent + `--run-file`; other dir → wandb_dir; nonexistent → error exit 1.
- `http(s)://` PATH → remote mode: URL must be `<scheme>://<host>/<entity>/<project>[/runs]/<run_id>`; `wandb.ai` host rewritten to `api.wandb.ai`; query/fragment dropped; auth via `wbauth.authenticate_session` (API key required) and passed as env `WANDB_API_KEY` (never argv); core invoked with `--remote-url <canonical-url>`.
- Base args always prepended: `--no-observability` when error reporting disabled; `--log-level -4` when `WANDB_DEBUG`. Wrapper `subprocess.run`s `wandb-core leet …` and exits with its return code.

### 1.2 `wandb-core leet` flag parsing (main.go `bindLeetFlags`) — the clap compatibility snapshot

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `<wandb-directory>` (positional, `fs.Arg(0)`) | string | `""` | Path to wandb dir containing run folders |
| `--log-level` | int | `0` | -4 debug, 0 info, 4 warn, 8 error; `-4` additionally writes JSON log `wandb-leet.debug.log` (truncate) in cwd |
| `--no-observability` | bool | `false` | Disables Sentry analytics (empty DSN) |
| `--run-file` | string | `""` | `.wandb` file to open directly in single-run view |
| `--pprof` | string | `""` | Serve `/debug/pprof/*` on this address |
| `--config` | bool | `false` | Open config editor |
| `--symon` | bool | `false` | Standalone system-metrics mode |
| `--interval` | duration | `2s` (`DefaultSymonSamplingInterval`) | Symon sampling interval (Go `time.ParseDuration` syntax: `500ms`, `2s`, `1m`) |
| `--remote-url` | string | `""` | W&B run URL, e.g. `https://api.wandb.ai/<entity>/<project>/runs/<run-id>` |

### 1.3 Validation and process behavior (main.go)

- Validation order: `--remote-url` must parse (`ParseRemoteURL`); `--interval > 0`; `--run-file` × `--remote-url` mutually exclusive; `--remote-url` takes no wandb dir; `--symon` takes no wandb dir; otherwise a wandb dir or `--remote-url` is required unless `--config`/`--symon`. Each failure prints `Error: …` + usage to stderr.
- Exit codes: `0` success (incl. `-h`), `1` internal error, `2` bad args.
- Dispatch: `--config` → config editor program; `--symon` → symon program; else workspace/run program. Symon and workspace both run in a restart loop: while final model `ShouldRestart()` (alt+r), recreate the model and rerun.
- Sentry: `CaptureMessage` of `wandb-leet` / `wandb-leet-config` / `wandb-symon` on start; flush 2s on exit (see §4).

## 2. Feature checklist

### 2.1 App shell & startup (model.go, help.go, animation.go, focusmanager.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| SH-01 | Flag parse/validation matrix + exit codes | main.go | unit-diff | unit/cli-flags-01 | pending |
| SH-02 | Startup `workspace_latest` (default): workspace view, latest run auto-focus after first dir poll | model.go | pty | pty/startup-workspace-01 | pending |
| SH-03 | Startup `single_run_latest`: `latest-run` symlink → run dir → `run-<id>.wandb` via `run-\d{8}_\d{6}-` regex (also `offline-run-`) | model.go | unit-diff | unit/latest-run-link-01 | pending |
| SH-04 | `--run-file` opens single-run view directly | model.go | pty | pty/startup-runfile-01 | pending |
| SH-05 | `--remote-url` remote mode (workspace Init suppressed, run view only) | model.go | live | live/remote-01 | pending |
| SH-06 | alt+r restart: `ShouldRestart` + outer relaunch loop (workspace & symon) | model.go, main.go | pty | pty/restart-01 | pending |
| SH-07 | Window title `wandb leet`, alt-screen on, mouse cell-motion mode | model.go | proto | proto/screen-modes-01 | pending |
| SH-08 | Background color query on init; `SetDarkBackground` from response; default dark=true | model.go, styles.go | proto | proto/osc11-01 | pending |
| SH-09 | q/ctrl+c quit with full Cleanup (watchers, readers, heartbeat) | model.go | pty | pty/quit-01 | pending |
| SH-10 | Help overlay (h/?): per-mode keymap tables, ASCII art header, version, tips, scrollable; h/?/esc close, q/ctrl+c quit from help | help.go | pty | pty/help-01 | pending |
| SH-11 | enter → run view (only when run selector active); esc → back to workspace (blocked while filtering / media fullscreen); `awaitingInput` snapshotted pre-dispatch | model.go | pty | pty/mode-switch-01 | pending |
| SH-12 | Media pane view-state save/restore across workspace↔run transitions; shared MediaStore | model.go, mediapane.go | pty | pty/mode-switch-02 | pending |
| SH-13 | Pane animations: 150ms ease-out-cubic, 15ms frames, mid-flight reversal, SetExpanded resize semantics | animation.go | unit-diff | unit/animation-01 | pending |
| SH-14 | FocusManager: ordered regions, Tab wrap skipping unavailable, AdoptTarget (mouse), ResolveAfterAvailability/VisibilityChange | focusmanager.go | unit-diff | unit/focus-01 | pending |
| SH-15 | Nav intent table: w/s/a/d + arrows, N/pgup, n/pgdown, home/end single source of truth | nav.go | unit-diff | unit/nav-keys-01 | pending |

### 2.2 Workspace view (workspace.go, workspacehandlers.go, workspacedirwatcher.go, workspace_runcolors.go, runoverviewsidebar*.go, pagedlist.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| WS-01 | 3-region layout: runs sidebar / central stack (metrics→system→media→logs, em-dash separators) / overview sidebar; logo fallback; media fullscreen takeover | workspace.go | pty | pty/workspace-layout-01 | pending |
| WS-02 | Runs list rendering: zebra stripes, marks ○/●/▶ (pin > selected), run-color names, cursor styles (active/inactive), header count formats | workspace.go | pty | pty/workspace-runs-01 | pending |
| WS-03 | PagedList semantics: cross-page wrap on Up/Down, PageUp/Down wrap, Home/End, cursor clamp on resize | pagedlist.go | unit-diff | unit/pagedlist-01 | pending |
| WS-04 | space select/deselect run: async reader init on select; dropRun teardown (unpin, remove series, stop watcher, close reader, drop logs/stats/media state) | workspacehandlers.go | pty | pty/workspace-select-01 | pending |
| WS-05 | p pin/unpin: single pin, pin-selects-first, PromoteSeriesToTop z-order refreshed on new history | workspacehandlers.go | pty | pty/workspace-pin-01 | pending |
| WS-06 | Panel toggles 1/[/2/]/3/4 animated + persisted to config; sidebar widths recomputed for opposite sidebar | workspace.go | pty | pty/workspace-panels-01 | pending |
| WS-07 | tab/shift+tab cycle runs↔metrics↔system↔media↔logs↔overview; overview inner-section cycle first | workspacehandlers.go | pty | pty/workspace-nav-01 | pending |
| WS-08 | Key dispatch priority: runs filter > overview filter > metrics filter > system filter > grid-config digits > focused nav > keymap | workspacehandlers.go | pty | pty/workspace-nav-02 | pending |
| WS-09 | f runs filter: auto-expand sidebar, live preview, status `Runs filter (<mode>): <q>▒ [n/total]`, ctrl+f clear, cursor preservation | workspacerunfilter.go | pty | pty/workspace-filter-01 | pending |
| WS-10 | Run filter metadata index: partial RunMsg merge (keep prior fields), tags dedupe/trim, config flatten (dotted paths, `[i]` indices, sorted), fallback to run key | workspacerunfilter.go | unit-diff | unit/runfilter-index-01 | pending |
| WS-11 | Run colors: FNV-32a(runPath) into `GraphColors(ColorScheme)`; collision variants via HSL ring walk (hue ±17°/ring, 6 phases, L±0.035, S±0.05, reflect01, ≤1024); Release on delete | workspace_runcolors.go | unit-diff | unit/runcolors-01 | pending |
| WS-12 | Overview sidebar: header State/ID/Name/Project/Tags(badges)/Notes; sections Env/Config/Summary; dynamic heights (max 12/20/25, min 2, proportional squeeze, bottom-up extra) | runoverviewsidebar.go | pty | pty/workspace-overview-01 | pending |
| WS-13 | Overview o filter: key-or-value match, best-match section auto-focus, `Env: n, Config: m` info, ctrl+o clear, esc restore | runoverviewsidebarfilter.go | pty | pty/workspace-overview-02 | pending |
| WS-14 | Overview selection restore by key across refresh; section nav (tab sections, arrows, home/end) | runoverviewsidebarnav.go | unit-diff | unit/overview-nav-01 | pending |
| WS-15 | Workspace system-metrics pane: header + run label + nav info, min-height gating, "Select this run (Space)…" hints | workspacesystemmetricspane.go | pty | pty/workspace-sysmetrics-01 | pending |
| WS-16 | Run discovery: 5s dir poll, `run-`/`offline-run-` prefixes, sort desc by `20060102_150405` timestamp then name | workspacedirwatcher.go | pty | pty/workspace-newrun-01 | pending |
| WS-17 | Run deletion prune: dropRun, unpin, release color, drop overview/filter index, cancel queued preloads | workspacedirwatcher.go | pty | pty/workspace-delrun-01 | pending |
| WS-18 | Overview preload: FIFO dedup queue, ≤4 concurrent, scan ≤10 records/100ms for first RunMsg with ID | workspacedirwatcher.go | unit-diff | unit/preload-01 | pending |
| WS-19 | Run state lifecycle: Running on RunMsg; FileComplete → Finished(0)/Failed(≠0); stop per-run watcher; stop heartbeat when no live runs | workspacehandlers.go | pty | pty/workspace-lifecycle-01 | pending |
| WS-20 | Status bar: filter/grid-config prompts > composite (dir • filters • selection • focused chart detail); right `h: help` hidden while inputting | workspace.go | pty | pty/workspace-status-01 | pending |
| WS-21 | Mouse: sidebar clicks clear chart focus; band routing metrics/system/media/logs; click focus/unfocus; wheel zoom; right-drag inspect; alt sync | workspacehandlers.go | pty | pty/workspace-mouse-01 | pending |

### 2.3 Single-run view (run.go, runhandlers.go, runoverview.go, runfocus.go, flexlayout.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| RUN-01 | Layout: overview │ central flex stack │ system sidebar; `LowerTierRatio` 1/(1+φ) bottom split; right-then-left sidebar collapse when main < 10 cols | run.go, flexlayout.go | pty | pty/run-layout-01 | pending |
| RUN-02 | Golden-ratio sidebar widths: 0.382 single / 0.236 both, clamp [40,120] | flexlayout.go | unit-diff | unit/sidebar-width-01 | pending |
| RUN-03 | Panel toggles 1/[/]/2/3/4; single-animation-at-a-time token | run.go | pty | pty/run-panels-01 | pending |
| RUN-04 | tab cycle overview→metrics→media→logs→system with availability gates (expanded + has content) | runfocus.go | pty | pty/run-nav-01 | pending |
| RUN-05 | Nav routing per focus target: grids page/home/end, media scrub, logs scroll, overview item nav | runhandlers.go | pty | pty/run-nav-02 | pending |
| RUN-06 | c/r + digit grid config for focused pane (metrics/system/media), esc cancels, prompt text | runhandlers.go, config.go | pty | pty/run-gridcfg-01 | pending |
| RUN-07 | RunOverview flatten: nested maps → dotted sorted keys, slices → `key[i]`, env first-writer only, state strings incl. Crashed→"Error" | runoverview.go | unit-diff | unit/overview-flatten-01 | pending |
| RUN-08 | Boot load: chunked reads with progress in status bar; watcher+heartbeat armed only after boot completes for live runs | runhandlers.go | pty | pty/run-bootload-01 | pending |
| RUN-09 | Status bar: filter prompts, grid-config, last error, load progress, media label, focused chart title + view-mode + scale labels | run.go | pty | pty/run-status-01 | pending |
| RUN-10 | Mouse routing: sidebar/media/grid bands, click focus toggle (re-click unfocuses), wheel zoom, right-drag inspect, alt page-wide sync, focus adoption | runhandlers.go | pty | pty/run-mouse-01 | pending |

### 2.4 Charts (epochlinechart.go, timeserieslinechart.go, frenchfries*.go, metricsgrid.go, systemmetricsgrid.go, panelgrid.go, systemmetrics.go, units.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| CH-01 | Braille line rendering, Bresenham segments, opaque compositing (painter's order, no color blending) | epochlinechart.go | unit-diff | unit/canvas-braille-01 | pending |
| CH-02 | Multi-series overlay: lazy series, draw order, PromoteSeriesToTop, RemoveSeries + bounds recompute | epochlinechart.go | unit-diff | unit/canvas-multiseries-01 | pending |
| CH-03 | Gap insertion for NaN/Inf/out-of-view values | epochlinechart.go | unit-diff | unit/canvas-gaps-01 | pending |
| CH-04 | Log-Y: positive-data gate, log10 range + 0.1 min margin, ≤0 dropped, `[log]` suffix, tick un-log | epochlinechart.go | unit-diff | unit/logy-01 | pending |
| CH-05 | Linear Y padding: 10% floor 1e-6; zero-range cases 1e-4 / 10%·abs / 0.1; non-negative clamp | epochlinechart.go | unit-diff | unit/yrange-01 | pending |
| CH-06 | Nice X domain (min 20, round up to ×10), 4 X / 5 Y ticks, custom Y-label placement incl. extra top tick | epochlinechart.go | unit-diff | unit/axis-01 | pending |
| CH-07 | Wheel zoom: 10%/notch, min X-range 5, cursor-anchored, tail-anchor ≥0.95, view frozen (`isZoomed`) across new data | epochlinechart.go | unit-diff | unit/zoom-01 | pending |
| CH-08 | Inspection: hairline `│`, nearest point on topmost series (binary search ±1), legend `▬▬ x: y` 4 sig figs, left/right overflow flip, vertical centering | epochlinechart.go | unit-diff | unit/inspect-01 | pending |
| CH-09 | Synced inspection: alt+right-drag broadcasts InspectAtDataX to all visible charts, release ends all | metricsgrid.go | pty | pty/inspect-sync-01 | pending |
| CH-10 | Title truncation with separator-preferring ellipsis (`/ _ . - :`) | epochlinechart.go | unit-diff | unit/title-trunc-01 | pending |
| CH-11 | Park/dirty lifecycle: offscreen charts shrink to 1×1, DrawIfNeeded only visible page | metricsgrid.go | unit-diff | unit/park-01 | pending |
| CH-12 | TimeSeries: tail window (config default 10m), view modes `all history` / `live tail Xm` / `frozen X`, compactDuration, right pad clamp 2–10s | timeserieslinechart.go | unit-diff | unit/tailwindow-01 | pending |
| CH-13 | TimeSeries zoom reconcile: zoom-out re-engages tail/show-all; fixed window freezes | timeserieslinechart.go | unit-diff | unit/tailwindow-02 | pending |
| CH-14 | Time axis: span-dependent layouts (≥48h / ≥1h / else), endpoint-only labels when width-constrained; inspection `15:04:05 <v>` labels | timeserieslinechart.go | unit-diff | unit/time-axis-01 | pending |
| CH-15 | French-fries heatmap: fixed-width bucket averaging, MinY/MaxY (fallback 0–100) palette normalize, band layout + label column, bottom time row, row cap keeps last series, `[a,…,z/N]` detail | frenchfrieschart.go | unit-diff | unit/fries-01 | pending |
| CH-16 | Fries inspection: hairline, per-band `label: value` or `—`, bold bucket-timestamp label | frenchfrieschart.go | unit-diff | unit/fries-02 | pending |
| CH-17 | Toggle chart: feed both charts, sync view window from line chart, zoom always on line, log suppressed in heatmap, ScaleLabel `heatmap` | frenchfriestogglechart.go | unit-diff | unit/fries-toggle-01 | pending |
| CH-18 | y-key cycling: main charts log toggle only; heatmap-capable system charts linear→log→heatmap→linear | metricsgrid.go, systemmetricsgrid.go | pty | pty/chart-mode-01 | pending |
| CH-19 | MetricsGrid: alphabetical order, chart auto-create on first metric, stable palette color by title, per-series vs per-plot color mode | metricsgrid.go | unit-diff | unit/metricsgrid-01 | pending |
| CH-20 | Grid math: EffectiveGridSize clamp-down (never expand), ComputeGridDims cell/inner sizes, GridNavigator wraparound + PageBounds | panelgrid.go | unit-diff | unit/gridmath-01 | pending |
| CH-21 | Grid focus: preserved by title across updates, NavigateFocus row/col clamped to non-nil cells | metricsgrid.go | unit-diff | unit/gridfocus-01 | pending |
| CH-22 | System metric grouping: ExtractBaseKey (gpu.0.temp→gpu.temp, disk.io_per_device, tpu.hloExecTiming…), ExtractSeriesName (GPU 0, Core N, `<disk> read/write`, PROC Process N) | systemmetrics.go | unit-diff | unit/sysmetric-keys-01 | pending |
| CH-23 | MetricDef regex table: full CPU/mem/disk/net/GPU/TPU/IPU/Trainium coverage, `(/l:.+)?` suffix, most-specific-first order | systemmetrics.go | unit-diff | unit/sysmetric-defs-01 | pending |
| CH-24 | System chart colors: per-series (palette[0] base) vs per-plot (advancing), anchored multi-series provider | systemmetricsgrid.go | unit-diff | unit/syscolors-01 | pending |
| CH-25 | System chart header: title + `[N]` detail + `[log]`/`[heatmap]`, drop mode-then-detail when narrow | systemmetricsgrid.go | unit-diff | unit/sysheader-01 | pending |
| CH-26 | Unit formatting: 3 sig figs, `%`, `°C`, W→kW, MHz→GHz, binary B/KiB/MiB/GiB/TiB, decimal B/s rates, SI axis ticks (μ…Y) width-fitted | units.go | unit-diff | unit/units-01 | pending |
| CH-27 | Right sidebar (run view): SystemMetricsGrid host, header nav info, mouse offset math, StatsMsg processing | rightsidebar.go | pty | pty/run-sysmetrics-01 | pending |

### 2.5 Symon (symon.go, symonsampler.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| SYM-01 | Standalone model: 1-line header, status `symon • N charts • …`, help mode symon | symon.go | pty | pty/symon-01 | pending |
| SYM-02 | Keys: nav/pages/home/end, y mode cycle, `\` filter + `ctrl+\` clear, c/C r/R grid config, alt+r restart loop | symon.go | pty | pty/symon-02 | pending |
| SYM-03 | Mouse: hit test excludes header/status rows; wheel zoom, right-drag inspect, alt sync all | symon.go | pty | pty/symon-03 | pending |
| SYM-04 | Sampler: 2s default interval, system(host-wide, `/` disk) + optional XPU, concurrent with panic recovery, single timestamp per pass, schedule-after-process (no overlap), Cleanup closes resources | symonsampler.go | live | live/symon-01 | pending |

### 2.6 Media (media.go, mediapane.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| MED-01 | Media path resolution: absolute pass-through; relative → `<run-dir>/files/<clean-rel>` | media.go | unit-diff | unit/media-path-01 | pending |
| MED-02 | Glyph renderer (ANSI half-block) with per-(path,w,h) cache | mediapane.go | unit-diff | unit/media-glyph-01 | pending |
| MED-03 | Kitty renderer: support detection (probe + KITTY/WEZTERM/GHOSTTY/TERM_PROGRAM/TERM envs), image IDs from 10000, cell-size query, delete-on-toggle, async prepare, park frees | mediapane.go | proto | proto/kitty-01 | pending |
| MED-04 | k toggles glyph↔Kitty (no-op when unsupported); l toggles linked scrub | mediapane.go | pty | pty/media-render-01 | pending |
| MED-05 | Grid mode: rows×cols config, tile min 18×8, header `[a-b of n]` + run label, slider `━●─` with `X: _step v … i/n` + `[sync]`, pagination | mediapane.go | pty | pty/media-grid-01 | pending |
| MED-06 | Fullscreen: enter/esc, single image, footer caption/dimensions/format/step | mediapane.go | pty | pty/media-full-01 | pending |
| MED-07 | Scrubbing: per-series cursor + auto-follow newest; ←/→ ±1, ↑/↓ ±10, home/end; last-value (≤X) resolution | mediapane.go | unit-diff | unit/media-scrub-01 | pending |
| MED-08 | Linked scrub: union X cursor, binary-search alignment on toggle | mediapane.go | unit-diff | unit/media-scrub-02 | pending |
| MED-09 | Tile selection: a/d/w/s 2D move, click hit-test; pgup/pgdn series pages | mediapane.go | pty | pty/media-select-01 | pending |
| MED-10 | Status label: `Media: <key>` + step + caption(≤48) + sync/fullscreen markers | mediapane.go | pty | pty/media-status-01 | pending |

DIVERGENCE (recorded 2026-07-25, picture.rs review; amends MED-02/MED-03/TERM-01):
media image decoding is not bit-exact for two source classes. (1) JPEG: Go scales
`*image.YCbCr` inline with integer BT.601 math (x/image/draw impl.go:5854+) while the
Rust `image` crate converts YCbCr→RGB during decode with its own rounding. (2) Sources
decoding to more than 8 bits per channel (e.g. 16-bit PNG → `*image.NRGBA64`/
`*image.Gray16`): Go's kernel scaler dispatches them at full 16-bit precision via the
`image.RGBA64Image` path (impl.go:5615-5617); the Rust port quantizes to RGBA8 first
(`SourceImage::from_dynamic`, `crates/leet-tui/src/picture.rs`). Rendered half-block/
Kitty pixels may differ by ±1 channel step for such inputs; 8-bit PNG/GIF sources are
bit-exact.

NOTE (FMA platform pin, 2026-07-25, amends MED-02): the imaging Box resize
accumulators in `crates/leet-tui/src/picture.rs` (`resize_horizontal`/
`resize_vertical`) use `f64::mul_add` to match Go (gc) on arm64, which fuses
`acc += x*y` into FMADDD (differentially verified: 39/300 randomized Glyph frames show
±1 channel diffs unfused, 0 fused; regression test
`box_resize_accumulators_fuse_like_go_arm64`). Go on amd64 without GOAMD64>=v3 does
not fuse; an amd64-hosted oracle would need the unfused form. Only reachable when Box
weights are not exact binary fractions — the default 8×16 test-mode cell size never
diverges, real terminal cell sizes (e.g. 10×20) do.

Phase-5 NOTE (amends MED-03, do not drop): Kitty capability resolution needs THREE
pieces wired in the app shell — the `QueryKittySupport` probe (env preflight → 1×1
`a=q` APC + timeout tick, picture/kitty_capability.go:116-140), picture's
`kittyEnvSignal` (kitty_capability.go:142-176), AND mediapane's
`terminalSignalsKittyGraphics` (mediapane.go:1234-1252, consulted by
`ensureKittyGraphicsEnabled` mediapane.go:1223-1231 only after honoring an affirmative
probe result). The two env heuristics differ (only mediapane's checks GHOSTTY_BIN_DIR
and lowercases TERM_PROGRAM/TERM before matching); porting only one silently drops
Kitty mode on terminals the other recognizes. `crates/leet-tui/src/picture.rs` ports
only the capability state (`kitty_supported`/`force_kitty_capability`).

DIVERGENCE (recorded 2026-07-26, Kitty runtime wiring; amends MED-03, mechanism only —
observable behavior preserved): Go emits the CSI 16 t / OSC 11 / Kitty `a=q` queries
as `tea.Raw` cmds and ultraviolet decodes the async replies on the input path.
crossterm-0.29 cannot do that: the `CSI 6;h;w t` and OSC 11 replies error out of its
parser and are dropped, and the APC response would decode as garbage key presses
(ESC-prefix alt-key fallback). The runtime therefore performs ONE `/dev/tty`
round-trip at startup — before the singleton input thread owns the tty — writing the
byte-exact Go queries (env-preflighted probe included) behind a DA1 fence, and
replays the captured replies when the media pane's Init commands are dispatched:
`Event::CellSize` (ack `uv.CellSizeEvent`), `Event::KittyGraphics` (ack
`uv.KittyGraphicsEvent`) plus the armed 250ms `Event::KittyProbeTick` (ack
`picture.kittyProbeTickMsg`), which drive the ported recordKittyResponse/
recordKittyTimeout state machine (media_pane.rs). `applyKittyGridMsg` has no Event
variant: the grid is applied synchronously after queueing the `tea.Raw` APC write,
which preserves Go's tea.Sequence on-wire order (write dispatches before the next
draw). Cell size is captured once per process; a mid-session terminal font-size
change is not re-detected (Go re-queries per media-pane Init). All of this is
suppressed in test mode, so Tier-2 scenarios are unaffected.

### 2.7 Console logs (runconsolelogs.go, consolelogspane.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| LOG-01 | Dual terminal emulators (stdout/stderr), 64-line cursor window, 4096-rune lines, arrival-order interleave, full history retained | runconsolelogs.go | unit-diff | unit/logs-emu-01 | pending |
| LOG-02 | Escape handling exactly: `\r`, `\n`(implies CR), `ESC[A`, `ESC[B`; all other escapes written literally (tqdm-oriented, no SGR) | runconsolelogs.go | unit-diff | unit/logs-emu-02 | pending |
| LOG-03 | Timestamp key `15:04:05`, trailing-space trim on update | runconsolelogs.go | unit-diff | unit/logs-emu-03 | pending |
| LOG-04 | Pane layout: 0.12 key-column ratio, adaptive HH:MM:SS→HH:MM→blank, display-width wrapping, ellipsis on overflow | consolelogspane.go | unit-diff | unit/logs-pane-01 | pending |
| LOG-05 | Auto-scroll tail: default on, disengage on manual nav, wrap-around up/down, page by wrapped lines, home/end set/clear | consolelogspane.go | pty | pty/logs-scroll-01 | pending |

### 2.8 Filters & run query language (filter.go, metricsfilter.go, systemmetricsfilter.go, runfilterquery.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| FLT-01 | Filter widget: draft/applied, Activate/Commit/Cancel/Clear, Tab regex↔glob, rune-aware backspace, live Query() | filter.go | unit-diff | unit/filter-widget-01 | pending |
| FLT-02 | Matching: case-insensitive unanchored; glob `*`/`?` auto-wrapped; regex `(?i)` with substring fallback (no metachars or compile error); empty matches all | filter.go | unit-diff | unit/filter-match-01 | pending |
| FLT-03 | Grid filter application: title match, pagination update, `[matched/total]` indicators, clear resets focus | metricsfilter.go, systemmetricsfilter.go | pty | pty/metrics-filter-01 | pending |
| FLT-04 | Query tokenizing: whitespace split, `"`/`'` quoting, `\` escapes; OR via `\|`/`or`, implicit AND (`and` ignored), `not` + `-`/`!` prefixes (stacking toggles); groups = OR of AND-clauses | runfilterquery.go | unit-diff | unit/runquery-01 | pending |
| FLT-05 | Fields: name/run_name/display/display_name; key/run_key/path; id/run_id; project; note/notes; tag/tags; config/cfg; config.<path>/cfg.<path> (lowercased); `has:`/`exists:` existence | runfilterquery.go | unit-diff | unit/runquery-02 | pending |
| FLT-06 | Operators (leftmost, longest-match): `:` pattern (mode-aware; config matches path/value/`path=value`), `=` case-fold exact, `!=`, `>` `>=` `<` `<=` numeric (single-value fields only; non-numeric rhs → false) | runfilterquery.go | unit-diff | unit/runquery-03 | pending |
| FLT-07 | Bare term searches RunKey/DisplayName/ID/Project/Notes/Tags; unparseable clauses fall back to bare term | runfilterquery.go | unit-diff | unit/runquery-04 | pending |

DIVERGENCE (see PORTING.md module mapping): `filter.go` is split across crates — the
pure matcher subset (`FilterMatchMode`, `compileTextMatcher`, glob/wildcard/hasRegexMeta;
covers FLT-02) lives in `leet-data::run_filter_query`; the `Filter` widget and key
handling (FLT-01) port to `leet-tui`, which must reuse/re-export the `leet-data` matcher
rather than re-port it.

### 2.9 Config & editor (config.go, configeditor.go, configeditorfields.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| CFG-01 | Config schema: all 28 fields (startup_mode; 8 grid structs rows/cols; 5 color schemes; 2 color modes; system_tail_window_minutes; heartbeat_interval_seconds; 10 visibility bools) with exact snake_case JSON keys and Go defaults | config.go | unit-diff | unit/config-schema-01 | pending |
| CFG-02 | Path resolution: `$WANDB_CONFIG_DIR` → `~/.config/wandb` → `os.UserConfigDir()/wandb` → mkdtemp → `TempDir()/wandb-leet.json`; writability probe (mkdir+tempfile); `~` expansion | config.go | unit-diff | unit/config-path-01 | pending |
| CFG-03 | Load/normalize (grid clamp 1–9, invalid enums/intervals → defaults), write defaults on first run, atomic save `.tmp`+rename, indent 2 | config.go | unit-diff | unit/config-io-01 | pending |
| CFG-04 | Pending grid-config: 14 targets, digit 1–9 apply, prompt/status text, setters persist immediately | config.go | pty | pty/gridcfg-01 | pending |
| CFG-05 | Editor: schema from `leet:` tags (label/desc/min/max/options/`-`), string fields need enum provider, group desc inheritance, sentence-case labels | configeditorfields.go | unit-diff | unit/cfgedit-schema-01 | pending |
| CFG-06 | Editor UI: browse/enum/int modes, ↑↓/kj move, ←→/hl bump (bool toggle, int clamp, enum wrap), enter/space activate, int validation errors, s/ctrl+s save&quit, dirty `*` + two-step quit confirm texts | configeditor.go | pty | pty/cfgedit-01 | pending |
| CFG-07 | Palette preview: `█` swatch per color for colorScheme enums, adaptive fg | configeditor.go | pty | pty/cfgedit-02 | pending |

### 2.10 Styling & theming (styles.go)

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| STY-01 | 14 palettes byte-exact (sunset-glow, blush-tide, gilded-lagoon, bootstrap-vibe, wandb-vibe-10/20, dusk-shore, clear-signal, traffic-light, viridis, plasma, inferno, magma, cividis); sequential ones uniform light/dark | styles.go | unit-diff | unit/palettes-01 | pending |
| STY-02 | AdaptiveColor light/dark resolution via cached background flag (default dark) | styles.go | unit-diff | unit/adaptive-01 | pending |
| STY-03 | Zebra odd-row bg: one-shot termenv bg query, 5% blend toward gray; fallback `#d0d0d0`/`#1c1c1c` | styles.go | live | live/zebra-01 | pending |
| STY-04 | Tag badges: FNV color hash + WCAG-contrast fg (white vs `#171717`) per variant | styles.go | unit-diff | unit/tagcolor-01 | pending |
| STY-05 | Layout constants (StatusBarHeight 1, min chart 20×5 / metric 18×4, borders, golden ratios) and separator/border glyphs (`│`, em-dash rules) | styles.go | unit-diff | unit/layout-consts-01 | pending |

### 2.11 Live data & terminal integration

| ID | Feature | Go source | Layer | Scenario | Status |
|---|---|---|---|---|---|
| LIVE-01 | Chunk constants: boot 1000/100ms, live 2000/50ms; Read stops at count or deadline | historysource.go | unit-diff | unit/chunks-01 | pending |
| LIVE-02 | Record→msg mapping: Run/History/Stats/Summary/Environment/OutputRaw/Exit; all other record types dropped; per-chunk History+Summary concatenation | leveldbhistorysource.go | unit-diff | unit/record-stream-01 | pending |
| LIVE-03 | History parsing: media field-suffix set (_type/path/caption/format/width/height/sha256/size/count/filenames/captions), `image-file` single point, `images/separated` fan-out `key[i]`, unknown _type dropped | leveldbhistorysource.go | unit-diff | unit/record-stream-02 | pending |
| LIVE-04 | `_step` extraction, `_`-prefixed keys dropped, non-numeric values dropped, JSON string unquoting | leveldbhistorysource.go | unit-diff | unit/record-stream-03 | pending |
| LIVE-05 | Exit → FileCompleteMsg{ExitCode} exactly once; hasMore=false after exit; post-exit reads → empty + EOF | leveldbhistorysource.go | unit-diff | unit/record-stream-04 | pending |
| LIVE-06 | Tail resume: ErrUnexpectedEOF→EOF remap, ResetLastRead rewind on any error, Recover on corrupt tail | livestore.go | unit-diff | unit/tail-resume-01 | pending |
| LIVE-07 | Heartbeat: generation-counter stale-callback guard, arm only when running, Reset on every data/file msg, fire → live read + watcher re-arm, non-blocking send | heartbeat.go | unit-diff | unit/heartbeat-01 | pending |
| LIVE-08 | File watcher: 500ms poll, Write+Create ops only, non-blocking FileChangedMsg, Finish unblocks waiter | watchermanager.go | unit-diff | unit/watcher-01 | pending |
| LIVE-09 | Parquet remote source: bootstrap RunMsg+synthesized SummaryMsg, 100-step pages, maxStep from summary `_step` (empty-page stop when unknown), FileComplete always exit 0, float/int/uint values only, no stats/media/logs | parquethistorysource.go | live | live/remote-02 | pending |
| LIVE-10 | Remote URL parsing: 3-seg and 4-seg(`runs`) forms only, http/https, host required, trailing slash ok; extracts BaseURL/Entity/Project/RunID (no host canonicalization in core) | remote.go | unit-diff | unit/remote-url-01 | pending |
| LIVE-11 | `WANDB_API_KEY` env required in remote mode; hard error msg when unset | parquethistorysource.go | unit-diff | unit/remote-auth-01 | pending |
| TERM-01 | Kitty APC image transmission/delete sequences byte-compatible | mediapane.go | proto | proto/kitty-02 | pending |
| TERM-02 | OSC 11 request + response parse (light/dark switch live) | model.go, styles.go | proto | proto/osc11-02 | pending |
| TERM-03 | SGR mouse cell-motion enable/disable on enter/exit | model.go | proto | proto/mouse-mode-01 | pending |
| TERM-04 | Text-input cursor visibility/placement in filter and int-edit inputs | filter.go, configeditor.go | live | live/cursor-01 | pending |
| TERM-05 | shift+drag native text selection passthrough (no app handling) | keybindings.go | live | live/select-01 | pending |

## 3. Data-behavior contracts (non-visual, must hold under differential record-stream tests)

- **Tail-resume on partial records**: a torn/unexpected-EOF trailing record behaves exactly like EOF; the read offset rewinds (`ResetLastRead`) so the same record is retried on the next read; recovery skips corrupt data so progress resumes.
- **FileComplete exactly once**: `FileCompleteMsg{ExitCode}` is appended to the batch on the read that observes the Exit record and never again; subsequent reads return empty batches with EOF.
- **Chunk bounds**: a single `Read` never exceeds `chunkSize` records nor `maxTimePerChunk` wall time; boot = 1000/100ms, live = 2000/50ms; HistoryMsgs and SummaryMsgs within a chunk are concatenated into one message each.
- **Heartbeat only-when-quiet**: heartbeat arms only while the run is live and is reset by every incoming data or file-change message, so it fires only after `heartbeat_interval_seconds` (default 15, min 1) of silence; generation counter prevents stale timer callbacks after Stop/Reset.
- **Watcher may miss the final change**: the 500ms mtime poller gives no guarantee the last write is observed; the heartbeat is the mandated safety net that forces a final catch-up read. Both properties must be preserved together.
- **Config JSON cross-compat**: the Rust binary must read/write the same `wandb-leet.json` (identical keys, clamping, normalization, atomic `.tmp`+rename) and resolve its path in the same order: `$WANDB_CONFIG_DIR` → `~/.config/wandb` → OS user config dir + `/wandb` → temp fallbacks, with the same writability probe. A config written by Go must round-trip through Rust unchanged (modulo field order) and vice versa.
- **Remote auth**: API key comes only from `WANDB_API_KEY` (set by the Python wrapper); no netrc lookup; missing key is an immediate user-facing error.

## 4. Explicit non-goals for v1 parity

The Rust binary must **accept** every flag in §1.2 (the Python wrapper passes them unconditionally), but the following behaviors are not required for parity sign-off:

- `--pprof ADDR`: Go serves `net/http/pprof`. Rust v1: accept and ignore (or serve its own profiler later). Must not error on the flag.
- `--no-observability` / Sentry: Go inits Sentry (LeetSentryDSN), sends `wandb-leet`/`wandb-leet-config`/`wandb-symon` breadcrumb message, flushes 2s at exit. Rust v1: accept the flag; telemetry itself is optional and off by default until wired.
- `--log-level -4` debug log: flag must parse and gate verbosity; emitting a byte-identical `wandb-leet.debug.log` JSON-lines file is not required (a Rust-native debug log at the same path is acceptable).
- Sentry panic capture / `CaptureError` plumbing: replace with Rust-native error logging; not diffed.
- ntcharts-internal quirks not observable in output (e.g. buffer pooling, `slices.Concat` avoidance) — only rendered output and asymptotics matter.
- Go `time.ParseDuration` error-message text for `--interval` (semantics must match; wording may differ).

Everything else in §2/§3 — including deliberately odd behaviors (console-log emulator writing unknown escapes literally, zebra 5% blend, `ctrl+l` legacy alias) — **is** in scope: this is a mechanical port, bug-for-bug.

## 5. Test-suite transliteration tracker

All `_test.go` files in `core/internal/leet` (46 files, 10,531 LOC total). Each row flips to `done` when the Rust equivalent lands and passes.

| Go test file | LOC | Target Rust crate | Status |
|---|---|---|---|
| animation_test.go | 121 | leet-tui | pending |
| config_test.go | 132 | leet-tui | pending |
| configeditor_test.go | 169 | leet-tui | pending |
| consolelogspane_test.go | 278 | leet-tui | pending |
| epochlinechart_multiseries_test.go | 240 | leet-charts | pending |
| epochlinechart_overlay_test.go | 234 | leet-charts | pending |
| epochlinechart_test.go | 409 | leet-charts | pending |
| filter_test.go | 29 | leet-tui | pending |
| focusmanager_test.go | 44 | leet-tui | pending |
| frenchfrieschart_test.go | 319 | split: leet-charts + leet-tui (§5.2) | done |
| heartbeat_lifecycle_test.go | 85 | leet-data | pending |
| heartbeat_test.go | 161 | leet-data | pending |
| leveldbhistorysource_test.go | 411 | leet-data | pending |
| liveread_test.go | 126 | split: leet-data + leet-tui (§5.1) | pending |
| livestore_test.go | 335 | leet-data | pending |
| media_test.go | 203 | leet-data | pending |
| mediapane_test.go | 812 | leet-tui | pending |
| metricsfilter_test.go | 348 | leet-tui | pending |
| metricsgrid_test.go | 361 | leet-tui | pending |
| navhelpers_test.go | 72 | leet-tui | pending |
| navtesthelpers_test.go | 1 | leet-tui (helper) | pending |
| pagedlist_test.go | 72 | leet-tui | pending |
| panelgrid_test.go | 260 | leet-tui | pending |
| parquethistorysource_test.go | 216 | leet-remote | pending |
| remote_test.go | 84 | leet-remote | pending |
| rightsidebar_test.go | 123 | leet-tui | pending |
| run_update_test.go | 609 | leet-tui | pending |
| runconsolelogs_test.go | 53 | leet-tui | pending |
| runfilterquery_test.go | 181 | leet-data | pending |
| runhandlers_test.go | 251 | leet-tui | pending |
| runoverview_test.go | 120 | leet-tui | pending |
| runoverviewsidebar_test.go | 416 | leet-tui | pending |
| symon_keyhandling_test.go | 111 | leet-symon | pending |
| symon_test.go | 55 | leet-symon | pending |
| systemmetrics_test.go | 109 | leet-charts | pending |
| systemmetricsfilter_test.go | 57 | leet-tui | done |
| systemmetricsgrid_test.go | 151 | leet-tui | done |
| timeserieslinechart_test.go | 239 | leet-charts | pending |
| timeserieslinechart_zoom_test.go | 198 | leet-charts | pending |
| tui_test.go | 803 | SUPERSEDED-BY-HARNESS (§5.3) | done |
| watchermanager_test.go | 53 | leet-data | pending |
| workspace_keyhandling_test.go | 832 | leet-tui | pending |
| workspace_runcolors_test.go | 107 | leet-tui | pending |
| workspace_test.go | 254 | leet-tui | pending |
| workspacedirwatcher_preload_test.go | 76 | leet-tui | pending |
| workspacedirwatcher_test.go | 211 | leet-tui | pending |

### 5.1 Deferred cross-module cases from `liveread_test.go`

`liveread_test.go` exercises layers above `LiveStore` (which was ported to `leet-wire`
together with `livestore_test.go`), so none of its 6 cases could compile in `leet-wire`:
they cover `ReadRecords` (historysource.go:49), `Run.ReadLiveBatchCmd` (runhandlers.go:820),
`Workspace.ReadAvailableCmd` (workspacehandlers.go:486), and `ParseHistory`
(leveldbhistorysource.go:199), and depend on `tea.Msg`/`ConfigManager` types from unported
phases. They are deferred (see the `PARITY: DEFERRED TESTS` comment in
`crates/leet-wire/src/live_store.rs`); the units below MUST transliterate them 1:1. The
`liveread_test.go` row above flips to `done` only when all six exist and pass:

| Go case (liveread_test.go) | Function under test (Go) | Target port unit |
|---|---|---|
| TestReadRecords_PassesThroughArguments (:32) | ReadRecords (historysource.go) | leet-data `history_source` |
| TestRun_ReadLiveBatchCmd_WrapsChunkedBatchAndUsesLiveLimits (:41) | Run.ReadLiveBatchCmd (runhandlers.go) | leet-tui run |
| TestRun_ReadLiveBatchCmd_DropsEmptyChunk (:69) | Run.ReadLiveBatchCmd (runhandlers.go) | leet-tui run |
| TestWorkspace_ReadAvailableCmd_WrapsChunkedBatch (:80) | Workspace.ReadAvailableCmd (workspacehandlers.go) | leet-tui workspace |
| TestWorkspace_ReadAvailableCmd_DropsEmptyChunk (:108) | Workspace.ReadAvailableCmd (workspacehandlers.go) | leet-tui workspace |
| TestParseHistory_UsesHistoryStepFallback (:117) | ParseHistory (leveldbhistorysource.go) | leet-data `leveldb_history_source` |

Precedent: `media_test.go`'s four `TestParseHistory_*` cases are similarly deferred to the
`leet-data` `leveldb_history_source` unit (see the `PARITY: DEFERRED TESTS` comment in
`crates/leet-data/src/media.rs`).

### 5.2 Deferred cross-module cases from `frenchfrieschart_test.go`

The seven `TestFrenchFriesChart_*` cases of `frenchfrieschart_test.go` are transliterated
in `crates/leet-charts/src/french_fries_chart.rs`. The three `TestSystemMetricsGrid_*`
cases in the same file (frenchfrieschart_test.go:149-245) construct a `SystemMetricsGrid`
with `ConfigManager`/`NewFocus`/`NewFilter` (leet-tui types), so they cannot compile in
`leet-charts`. They are deferred (see the `PARITY: DEFERRED TESTS` comment in
`crates/leet-charts/src/french_fries_chart.rs`); the leet-tui `system_metrics_grid` unit
MUST transliterate them 1:1 in addition to `systemmetricsgrid_test.go`'s own cases. The
`frenchfrieschart_test.go` row above flips to `done` only when all ten cases exist and pass:

| Go case (frenchfrieschart_test.go) | Pins | Target port unit |
|---|---|---|
| TestSystemMetricsGrid_CycleFocusedChartMode (:149) | y-key mode-cycle order linear→log→heatmap→linear on a heatmap-capable chart (CH-18) | leet-tui `system_metrics_grid` |
| TestSystemMetricsGrid_GPUUtilizationUsesFrenchFriesChart (:188) | gpu.N.gpu metrics auto-create a french-fries-capable chart (CH-15/CH-17) | leet-tui `system_metrics_grid` |
| TestSystemMetricsGrid_FrenchFriesUsesConfiguredPalette (:214) | ConfigManager `FrenchFriesColorScheme` plumbing reaches `colorForValue` (CH-15) | leet-tui `system_metrics_grid` |

DONE (2026-07-25): all three cases are transliterated in
`crates/leet-tui/src/system_metrics_grid.rs` (tests
`system_metrics_grid_cycle_focused_chart_mode`,
`system_metrics_grid_gpu_utilization_uses_french_fries_chart`,
`system_metrics_grid_french_fries_uses_configured_palette`) and pass; the
`frenchfrieschart_test.go` row above is flipped to `done` (all ten cases exist
and pass). Two test-only adaptations, each documented at the assertion site:
Go's `TestChartAt(r, c).IsLogY()` reaches the toggle's inner line chart, whose
`line` field is private cross-crate — in heatmap mode the test probes it by
flipping heatmap mode off/on (a state-preserving raw bool toggle); and Go's
`TestColorForValue(0)/(100)` probe is crate-private to leet-charts (its
0→first / 100→last mapping is pinned there by
`french_fries_chart_uses_provided_palette`), so the palette-plumbing case
asserts through the rendered canvas that every heatmap cell resolves from the
configured plasma palette and the value-0 series renders with `plasma[0]`.

### 5.3 tui_test.go — SUPERSEDED-BY-HARNESS

`tui_test.go`'s five cases are teatest integration tests (PORTING.md "What NOT to
port": the teatest accumulation-loop workarounds are superseded by the differential
harness). They drive the full Go program under a fake terminal and assert on rendered
frames — exactly what the PTY differential scenarios do against BOTH implementations,
with the oracle as the assertion instead of hand-maintained expectations. They are NOT
transliterated (decided 2026-07-25 with the model.rs/main.rs unit); coverage maps to
harness scenarios:

| Go case (tui_test.go) | Superseding coverage |
|---|---|
| TestLoadingScreenAndQuit (:89) | pty/quit-01 (SH-09) + pty/run-bootload-01 (RUN-08) |
| TestMetricsAndSystemMetrics_RenderAndSeriesCount (:110) | pty/run-layout-01 (RUN-01) + unit/canvas-multiseries-01 (CH-02) |
| TestWorkspace_MultiRun_SelectPinDeselect_OverlaySeriesCount (:354) | pty/workspace-select-01 (WS-04) + pty/workspace-pin-01 (WS-05) |
| TestConsoleLogsPanel_ToggleAppendAndNavigate (:471) | pty/workspace-panels-01 (WS-06) + console-log scenarios (LOG-*) |
| TestWorkspace_SystemMetricsPaneAndConsoleLogs (:722) | pty/workspace-sysmetrics-01 (WS-15) |

model.go itself has no Go unit-test file; the ported behaviors are pinned by new Rust
tests in `crates/leet-tui/src/model.rs` (mode switching incl. the awaitingInput
snapshot, restart flag, help routing, latest-run link resolution) and the CLI matrix in
`crates/leet/src/main.rs`.

DIVERGENCE (signed off 2026-07-25, amends LOG-03): console-log timestamp keys
render in UTC, not Go's local time (`time.Unix` → Local,
leveldbhistorysource.go:409-410). std has no local-time API, the workspace
denies unsafe_code, and no tz crate is in the dependency set. The harness pins
the oracle to TZ=UTC (equivalent: Go under empty TZ renders UTC). Revisit when
a tz crate (jiff preferred) is adopted workspace-wide — tracked for Phase 8.

DIVERGENCE (signed off 2026-07-25, amends CH-14): system-metric chart X-axis
ticks and inspection-legend timestamps render in UTC, not Go's local time
(`time.Unix(...).Local()`, timeserieslinechart.go:460, 512) — the same
rationale and harness contract as the LOG-03 divergence above; the harness
pins the oracle to TZ=UTC (`harness/leet-harness/src/pty.rs`). Implemented in
`crates/leet-charts/src/timeseries_line_chart.rs` (`time_unix_utc`, used by
`format_x_axis_tick` and `format_inspection_label`; `french_fries_chart.rs`
reuses the same helpers for its bottom time row and inspection labels).
Revisit together with LOG-03 when a tz crate is adopted — tracked for Phase 8.
