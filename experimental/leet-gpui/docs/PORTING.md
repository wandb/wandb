# From Bubble Tea to GPUI

The Go LEET in `core/internal/leet` is the behavioral spec for this app. This document maps its architecture onto gpui and records which parts are mechanical ports, which are adaptations, and which are new.

## What ports, what does not

| Layer | Go files | Here | How |
|---|---|---|---|
| Wire format | `core/pkg/leveldb`, `core/internal/transactionlog`, `livestore.go` | `leet-wire`, `leet-proto` | Mechanical port, reused from the leet-rs port verbatim |
| History parsing | `historysource.go`, `leveldbhistorysource.go`, `media.go` | `leet-data` | Mechanical port, reused verbatim |
| Run discovery | `workspacedirwatcher.go` | `leet-gpui/src/source.rs` | Adapted: directory scan on a timer instead of fsnotify, one reader thread per open run instead of tea.Cmd goroutines |
| Workspace state | `workspace.go`, `workspacehandlers.go`, `focusmanager.go`, `pagedlist.go` | `leet-gpui/src/workspace.rs` | Adapted: same selection, cursor, focus, paging, and filter semantics on a gpui entity |
| Keymap | `keybindings.go`, `nav.go` | `leet-gpui/src/actions.rs` | Same keys and descriptions, expressed as gpui actions and key contexts |
| Chart math | `epochlinechart.go` ranges and ticks | `leet-plot` | New: the terminal chart's braille geometry does not apply to pixels |
| Rendering | `styles.go`, lipgloss, ntcharts | `leet-gpui/src/chart.rs`, `theme.rs` | New |

The Bun-style differential harness (oracle frames diffed cell by cell) covers the first two rows only, and it already ran in the leet-rs port. Pixels have no oracle; the workspace row can be checked against Go with a state-level dump (cursor, selection, page, focus after a key script) if that ever pays for itself.

## Pattern map

| Bubble Tea | gpui |
|---|---|
| `tea.Model` with `Update` and `View` | `Entity<Workspace>` implementing `Render`; handlers mutate `&mut self` and call `cx.notify()` |
| `tea.Msg` from a reader goroutine | `SourceMsg` batches on a `futures::channel::mpsc` channel, drained by `cx.spawn` and applied with `this.update` |
| `tea.Cmd` running IO | `std::thread` producing into the channel (native); `cx.background_spawn` on the web |
| `tea.KeyPressMsg` switch in handlers | `actions!` types bound with `KeyBinding::new(key, action, Some(context))`, dispatched to `.on_action` listeners |
| `FocusManager` cycling panes | one `FocusHandle` on the root plus a `Pane` enum; the root's `key_context` switches to `Filter` while typing |
| `Filter` text box reading keys | `on_key_down` appending `keystroke.key_char` when a filter is editing |
| `tea.Tick` heartbeat | `cx.background_executor().timer(...)` in a `cx.spawn` loop |
| `computeViewports` and flex fractions | `div().flex()` with `flex_1` and fixed widths (taffy) |
| `lipgloss` styles | `Styled` builder methods; colors in `theme.rs` |
| ntcharts braille canvas | `canvas(prepaint, paint)` with `PathBuilder::stroke` and `window.paint_path` |
| `AnimatedValue` | not ported yet (`Animation` in gpui when needed) |

## Conventions

The paint closure reads the workspace through `Entity::read(cx)` rather than cloning series into the element tree. It gathers what it needs into owned decimated points first and paints second, so the immutable borrow of the app ends before text shaping needs `&mut App`.

Keys and their help text live in one table in `actions.rs`. The help overlay renders that table; there is no second list to drift.

Run colors are assigned when a run is selected: the lowest palette index no other selected run uses. This mirrors the intent of `workspace_runcolors.go` without its reservation table.
