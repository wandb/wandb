# PORTING.md — Go → Rust mechanical port guide for leet

The Go implementation at `core/internal/leet` is the **behavioral spec**. This is a
mechanical port: preserve architecture, algorithms, rendering output, and quirks. When Go
does something odd, port the oddity and leave a `// PARITY:` comment; do not "improve"
behavior. Improvements come after parity is proven (tracked separately).

Companion docs: `CONCURRENCY.md` (goroutine→thread mapping, prescriptive),
`PARITY.md` (feature checklist + scenario map, the definition of done).

## Module mapping

One Go file → one Rust module of the same snake_case name, in its assigned crate.
Do not merge or split files during the port (one recorded exception: `filter.go`,
see the DIVERGENCE note below the table).

| Go file(s) | Rust crate | Module |
|---|---|---|
| `core/pkg/leveldb/{record,crc}.go`, `core/internal/transactionlog/*`, `livestore.go` | `leet-wire` | `record`, `crc`, `transaction_log`, `live_store` |
| protobuf types (`spb`) | `leet-proto` | generated, committed |
| `historysource.go`, `leveldbhistorysource.go`, `media.go`, `runoverview.go` (+ used subset of `core/internal/{runconfig,runsummary,runenvironment}`) | `leet-data` | same-name modules |
| `systemmetrics.go`, `units.go`, `config.go`, `runfilterquery.go`, `remote.go` | `leet-data` | 〃 |
| `workspace_runcolors.go` | `leet-charts` | uses `AdaptiveColor`; charts may depend on data, not vice versa |
| `filter.go`, `metricsfilter.go`, `systemmetricsfilter.go` | `leet-tui` | take `tea.KeyPressMsg` / are `MetricsGrid` methods |
| `epochlinechart.go`, `timeserieslinechart.go`, `frenchfrieschart.go`, `frenchfriestogglechart.go`, ntcharts braille canvas subset | `leet-charts` | 〃 + `braille` |
| `styles.go` (palettes/adaptive colors) | `leet-charts` | `styles` |
| `metricsgrid.go`, `systemmetricsgrid.go`, panes, sidebars, `flexlayout.go`, `panelgrid.go`, `pagedlist.go`, `animation.go`, `help.go`, `mediapane.go`, `consolelogspane.go`, `runconsolelogs.go` + terminal emulator | `leet-tui` | 〃 |
| `model.go`, `workspace*.go`, `run*.go`, `focusmanager.go`, `keybindings.go`, `nav.go`, `messages.go`, `heartbeat.go`, `watchermanager.go`, `workspacedirwatcher.go` | `leet-tui` | 〃 |
| `symon.go`, `symonsampler.go`, `systemmetricsview.go` | `leet-symon` (+`leet-tui` for the view) | 〃 |
| `parquethistorysource.go`, `remote.go`, gql | `leet-remote` | 〃 |
| `configeditor.go`, `configeditorfields.go` | `leet-tui` | 〃 |
| `testhelpers.go` | not ported | see Testing below |

DIVERGENCE (recorded in PARITY.md §2.8): `filter.go` is split. Its pure text-matching
subset — `FilterMatchMode`, `compileTextMatcher`, `globMatchUnanchoredCaseInsensitive`,
`wildcardMatch`, `hasRegexMeta` (filter.go:11-29, 168-267) — is hosted in
`leet-data::run_filter_query`, because `runfilterquery.go` (a `leet-data` module) calls
`compileTextMatcher` and `leet-tui` depends on `leet-data`, not vice versa. The `Filter`
widget and its key handling port to `leet-tui` as mapped above and MUST reuse/re-export
`leet_data::run_filter_query::{FilterMatchMode, compile_text_matcher}` — do not re-port
the matcher (the two copies would drift).

## Architecture pattern map

| Go / Bubble Tea | Rust / ratatui | Notes |
|---|---|---|
| `tea.Model` impl (`Init/Update/View`) | struct + `fn init(&mut self) -> Vec<Command>`, `fn update(&mut self, Event) -> Vec<Command>`, `fn view(&self, &mut Frame)` | update/view on ONE thread; locks Go needed for concurrent View die (see CONCURRENCY.md) |
| `tea.Msg` (interface{}) | `enum Event` mirroring `messages.go` 1:1 | one variant per Go msg type, same names |
| `tea.Cmd` (func returning Msg) | `enum Command` + effect runner executing off-thread, result sent into the event mpsc | blocking pumps become dedicated threads |
| `tea.Batch(cmds...)` | `Vec<Command>` | order preserved |
| `tea.Tick(d, fn)` | scheduler arm (CONCURRENCY.md §2) | |
| `tea.KeyPressMsg` / `MouseMsg` | crossterm `KeyEvent` / `MouseEvent` normalized into `Event::Key`/`Event::Mouse` wrappers | keep leet's own binding tables (`keybindings.go`), do NOT re-key to crossterm names |
| `tea.WindowSizeMsg` | `Event::Resize{w,h}` | |
| interface `HistorySource` | `trait HistorySource` in `leet-data` | object-safe; `Box<dyn HistorySource>` |
| `lipgloss.Style` render | `Style` + explicit cell writes / span builders | port `flexlayout.go` verbatim; implement `join_horizontal/join_vertical/place` helpers replicating lipgloss alignment+padding arithmetic (padding cells are UNSTYLED spaces — Tier-2 parity depends on this) |
| `lipgloss.Width` | `text_width()` in `leet-data::width` (grapheme-aware shim, proptested vs Go) | never call `unicode_width` directly outside the shim |
| bubbles `viewport` (help only) | `Paragraph` + scroll offset | do not port bubbles |
| ntcharts `BrailleGrid`/`linechart` | `leet-charts::{canvas,braille}` — port ONLY the subset leet uses, verbatim | do not use ratatui `Chart`/`Canvas` |
| chart `View() string` (ANSI block) | render into `leet_charts::canvas::Canvas` (char + fg/style cell grid) | `leet-tui` blits canvases into the ratatui buffer; keeps leet-charts ratatui-free and unit-diffable against the Go rune grid |
| `CoreLogger` / observability | `tracing` behind a thin `Logger` facade | Sentry decision deferred to Phase 8 |

## Language-level rules

- **Errors**: Go `(T, error)` → `Result<T, Error>` with `thiserror` per crate; `anyhow`
  only in the bin and harness. A Go function that logs-and-continues keeps that shape —
  do not convert soft-fail paths into hard `?` bubbles.
- **Zero values**: Go relies on zero values; implement `Default` explicitly per struct and
  audit each field (a Go `0`/`""`/`nil` default that's meaningful must survive).
- **nil maps/slices**: reading a nil Go map yields zero value, writing panics; ranging a nil
  slice is a no-op. Rust `HashMap`/`Vec` defaults are empty and writable — behavior matches
  reads, watch for code that distinguishes nil vs empty (`== nil` checks port to `Option`).
- **Numeric**: Go ints are 64-bit here (`int`); use `i64`/`usize` deliberately at indexing
  boundaries. Go float→int conversion truncates toward zero and is UB-free; use `as` (same
  semantics) but check for the Go idiom `int(math.Round(x))` vs bare `int(x)`.
- **Strings**: Go `range str` yields runes → `str.chars()`. Go `len(str)` is BYTES →
  `str.len()`. Column math must go through the width shim, never `chars().count()`.
- **Maps**: Go map iteration order is RANDOM — any Go code that iterates then sorts is
  fine; any Go code that iterates WITHOUT sorting and the order reaches the screen is a
  latent Go bug: port with `BTreeMap`/sorted keys and leave `// PARITY: Go iterates
  unordered here; sorted for determinism` (also flag it in the PR description).
- **Sorting**: `sort.Slice` is UNSTABLE (`sort.SliceStable` is stable). Rust `sort_by` is
  stable, `sort_unstable_by` is not. Match stability semantics exactly — chart series
  order and run lists depend on it.
- **defer**: LIFO at function exit → explicit scope guards or restructure; for
  mutex-unlock defers, Rust guards handle it; for cleanup defers, prefer `Drop`.
- **append aliasing**: `append` may mutate the backing array of the source slice. Any Go
  code passing sub-slices around then appending needs careful reading — in Rust, clone at
  the boundary and note it.

## Formatting / text compat (parity-critical)

- All float→string formatting goes through `leet_data::go_fmt`:
  `go_fmt::format_float_g(v, prec)`, `format_float_f(v, prec)` — reimplementations of
  `strconv.FormatFloat('g'/'f')` including exponent-threshold and `e+06` exponent forms.
  Property-tested against a Go dump. Never `format!("{}")` a float that reaches a frame.
- `%d`, `%s`, `%q`, padding via `fmt.Sprintf` → `format!` is fine for ints/strings; `%q`
  → a `go_quote()` helper (Go's escaping differs from `{:?}`).
- Regex: Go `regexp` is RE2; Rust `regex` crate is compatible for leet's patterns (no
  backrefs/lookaround in either). Port patterns byte-for-byte; `(?i)` etc. carry over.
  `regexp.MustCompile` in package vars → `LazyLock<Regex>`.
- Time formatting: none renders from wall clock in test mode; console-log timestamps come
  from record data. Format with explicit layouts matching Go's (`15:04:05` → `%H:%M:%S`).

## Float math (parity-critical)

Go compilers may fuse `a*b + c` into FMA; Rust never fuses implicitly. When porting chart
math (`epochlinechart.go` scaling/quantization, braille dot placement):
- Keep the exact arithmetic shape with explicit temporaries: `let t = (x - min) * scale;`
  not algebraically-rearranged forms.
- `math.Round` → `f64::round` (both half-away-from-zero). `math.Trunc` → `trunc`.
  `math.Floor/Ceil` → `floor/ceil`. Integer division on negatives: Go truncates toward
  zero, Rust `/` too — but `%` sign follows the dividend in both; still, prefer
  `rem_euclid` ONLY when the Go code manually normalized negatives.
- NaN/±Inf: leet "poisons" ranges with non-finite values deliberately
  (`epochlinechart_test.go`); preserve comparisons exactly (`math.IsNaN` → `is_nan`;
  beware `NaN < x` is false in both, but Go `math.Min/Max` propagate NaN while
  `f64::min/max` IGNORE NaN — use explicit NaN checks when porting Min/Max).

## Testing conventions

- Each Go `_test.go` transliterates alongside its module: unit tests in `#[cfg(test)]`
  in-module; cross-module tests in `crates/<c>/tests/`.
- `testhelpers.go` (Go's exported accessors for black-box tests) is NOT ported as a shipped
  module. Rust tests use `pub(crate)` visibility; where the harness needs app introspection,
  add `#[cfg(feature = "test-hooks")]` accessors instead.
- `require.Equal(t, want, got)` → `assert_eq!(got, want)` (note the argument swap),
  `require.NoError` → `.unwrap()`/`expect` in tests, testify diffs → `pretty_assertions`.
- Table tests keep their Go case names as strings for grep-ability.

## Naming & style

- Go exported `CamelCase` → Rust `snake_case` fns / `CamelCase` types, same words: keep
  names 1:1 greppable (`drawBraillePatternsOccluded` → `draw_braille_patterns_occluded`).
- Keep Go comment text verbatim where it explains behavior; drop narration comments.
- Constants keep names and values (`AnimationDuration`, chunk sizes, palette hexes) —
  centralize in the module where Go declared them.
- `// PARITY:` marks intentional ports of quirks. `// DIVERGENCE:` marks approved
  deviations (each needs a PARITY.md row and reviewer sign-off).

## What NOT to port

- bubbles (viewport) — trivial paragraph scroll instead.
- ntcharts beyond the braille/canvas/axis subset leet actually touches.
- teatest workarounds (`tui_test.go` accumulation loop) — the harness supersedes them.
- purego/parquet FFI — `leet-remote` uses the `parquet` crate natively.
- `tea.Println`/debug scaffolding, `.DS_Store`-class strays, `tmpdumpmedia_main.go`.

## Attribution

`leet-charts::braille` and the lipgloss-style layout helpers derive from MIT-licensed
NimbleMarkets/ntcharts and charmbracelet/lipgloss — keep the MIT attribution header
comment at the top of those modules (template in `docs/ATTRIBUTION.md`).
