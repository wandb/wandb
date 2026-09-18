# From Bubble Tea to GPUI

The Go LEET in `core/internal/leet` is the behavioral spec for this app. This document maps its architecture onto gpui and records which parts are mechanical ports, which are adaptations, and which are new.

## What ports, what does not

| Layer | Go files | Here | How |
|---|---|---|---|
| Wire format | `core/pkg/leveldb`, `core/internal/transactionlog`, `livestore.go` | `leet-wire`, `leet-proto` | Mechanical port, reused from the leet-rs port verbatim |
| History and stats parsing | `leveldbhistorysource.go` | `leet-ingest` | Adapted: same key rules (dotted nested keys, `_` internals skipped, `_step` fallback), but records are folded into per-metric columns per batch instead of one message per record |
| Console output | `runconsolelogs.go` and its terminal emulator | `leet-ingest` | Adapted: escape sequences stripped, partial lines joined, carriage return restarts the line; no cursor addressing |
| System metric grouping | `systemmetrics.go`, `units.go` | `leet-data::system_metrics`, `units` | Mechanical port, reused verbatim: the definition table, base key and series name extraction |
| Run overview | `runoverview.go`, `core/internal/{runconfig,runsummary,runenvironment}` | `leet-data::run_overview` and friends | Mechanical port, reused verbatim |
| Run discovery | `workspacedirwatcher.go` | `leet-gpui/src/source.rs` | Adapted: directory scan on a timer instead of fsnotify, one reader thread per open run instead of tea.Cmd goroutines |
| Workspace state | `workspace.go`, `workspacehandlers.go`, `focusmanager.go`, `pagedlist.go` | `leet-gpui/src/workspace.rs`, `grid.rs` | Adapted: same selection, pin, cursor, focus, paging, filter, and pane semantics on a gpui entity |
| Layout | `computeViewports`, `flexlayout.go` | `Workspace::render` | Same structure and lower-tier ratio, pixel fractions instead of cells; no drag resizing yet |
| Keymap | `keybindings.go`, `nav.go` | `leet-gpui/src/actions.rs` | Same keys and descriptions, expressed as gpui actions and key contexts |
| Per-directory state | `dirstate.go` (branch `09-17-leet-remember-selected-runs`) | `leet-gpui/src/dir_state.rs` | Same file and keys, read and written through a JSON map so unknown keys survive |
| Config | `config.go` | `leet-gpui/src/config.rs` | Same key names where the meaning matches, in a separate file (`wandb-leet-gpui.json`) |
| Chart math | `epochlinechart.go` ranges and ticks | `leet-plot` | New: the terminal chart's braille geometry does not apply to pixels |
| Rendering | `styles.go`, lipgloss, ntcharts | `leet-gpui/src/chart.rs`, panes, `theme.rs` | New |

The Bun-style differential harness (oracle frames diffed cell by cell) covers the verbatim rows only, and it already ran in the leet-rs port. Pixels have no oracle; the workspace row can be checked against Go with a state-level dump (cursor, selection, page, focus after a key script) if that ever pays for itself.

## Pattern map

| Bubble Tea | gpui |
|---|---|
| `tea.Model` with `Update` and `View` | `Entity<Workspace>` implementing `Render`; handlers mutate `&mut self` and call `cx.notify()` |
| `tea.Msg` from a reader goroutine | `leet_ingest::Batch` on a `futures::channel::mpsc` channel, drained by `cx.spawn` and applied with `this.update` |
| `tea.Cmd` running IO | `std::thread` producing into the channel (native); `cx.background_spawn` on the web |
| `tea.KeyPressMsg` switch in handlers | `actions!` types bound with `KeyBinding::new(key, action, Some(context))`, dispatched to `.on_action` listeners |
| `FocusManager` cycling panes | one `FocusHandle` on the root plus a `Pane` enum; the root's `key_context` switches to `Filter` while typing |
| `Filter` text box reading keys | `on_key_down` appending `keystroke.key_char` when a filter is editing |
| `tea.Tick` heartbeat | `cx.background_executor().timer(...)` in a `cx.spawn` loop |
| `computeViewports` and flex fractions | `div().flex()` with `flex_1` and pixel widths from the viewport size (taffy) |
| `PagedList`, viewport scrolling | `uniform_list` with a `UniformListScrollHandle` |
| `lipgloss` styles | `Styled` builder methods; colors in `theme.rs` |
| ntcharts braille canvas | `canvas(prepaint, paint)` with `PathBuilder::stroke` and `window.paint_path` |
| `AnimatedValue` | not ported yet (`Animation` in gpui when needed) |

## Conventions

The paint closure reads series through `Entity::update(cx, ..)` on the workspace rather than cloning series into the element tree; the update refreshes the per-series caches and hands back owned decimated points, so the borrow ends before text shaping needs `&mut App`.

Keys and their help text live in one table in `actions.rs`. The help overlay renders that table; there is no second list to drift.

Run colors are assigned when a run is selected: the lowest palette index no other selected run uses. This mirrors the intent of `workspace_runcolors.go` without its reservation table.
