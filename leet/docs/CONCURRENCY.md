# CONCURRENCY.md — Go → Rust concurrency porting guide

Normative for all port agents. Verified against `core/internal/leet` at commit
`c37197bbd5` (this worktree). Bare `file.go:N` cites are relative to
`core/internal/leet/`; other paths are repo-relative. If line numbers drift,
anchor on the cited identifier, not the number.

Prime directive: the Go app multiplexes everything onto Bubble Tea's single
`Update` loop already. The Rust port makes that explicit: **one event loop owns
the model; everything else is a producer that sends `Event`s.** Most Go locks
exist only because Bubble Tea v2 may call `View` concurrently with `Update`, or
because `tea.Cmd` closures run on their own goroutines. Ratatui draws on the
update thread, so those locks are deleted, not ported.

---

## 1. Inventory (complete)

### 1.1 Channels and message pumps

| # | Construct | Producer(s) | Consumer (pump) | Semantics |
|---|-----------|-------------|-----------------|-----------|
| C1 | Run shared chan, `make(chan tea.Msg, 4096)` run.go:124; handed to both managers run.go:158-159 | watcher cb `select`+`default` drop watchermanager.go:42-47; heartbeat cb `select`+`default` drop heartbeat.go:48-53 | `WatcherManager.WaitForMsg` blocking recv watchermanager.go:83-90, run as a `tea.Cmd`; armed once after boot load runhandlers.go:908; re-armed per handled msg runhandlers.go:938 (heartbeat), runhandlers.go:950 (file change) | One in-flight delivery at a time; buffer absorbs bursts |
| C2 | Workspace `liveChan`, cap 4096 workspace.go:92, workspace.go:135, given to heartbeat mgr workspace.go:176 | heartbeat cb only (heartbeat.go:48-53) | `waitForLiveMsg` workspacehandlers.go:520-525; armed workspace.go:206, re-armed workspacehandlers.go:735, 741 | Heartbeat delivery for all live workspace runs |
| C3 | Per-run coalescing chan, `make(chan tea.Msg, 1)` workspacehandlers.go:541 (one per live workspace run) | that run's watcher cb, try-send+drop watchermanager.go:42-47 | `waitForWatcher` workspacehandlers.go:566-584 (watcher pointer captured on Update goroutine, :572-574); armed workspacehandlers.go:549, re-armed workspacehandlers.go:761 | cap-1 ⇒ burst of file changes coalesces to one notification |
| C4 | `Finish()` nil-send unblock: `select { case wm.outChan <- nil: default: }` watchermanager.go:70-74 | `WatcherManager.Finish` | pending `WaitForMsg` returns nil watchermanager.go:85-89; nil msg discarded by caller (workspacehandlers.go:577 checks `!= nil`) | Shutdown handshake for the blocked pump |
| C5 | Media prepare chan, `make(chan struct{}, 1)` mediapane.go:141, mediapane.go:153 | render path `requestRenderedMediaPrepare` try-send+drop mediapane.go:219-227 (called mediapane.go:245, 463) | `waitForPrepare` blocking recv mediapane.go:212-217; armed in `MediaPane.Init`, re-armed after each prepare mediapane.go:229-231 | Self-notify to run Kitty image prep after render; cap-1 coalesces. NOTE: Go never closes it — the pump goroutine leaks on view exit (benign in Go) |

No raw `go func` statements exist in the leet package (verified by grep); all
concurrency is via `tea.Cmd` goroutines, the two managers, `errgroup`
(symonsampler.go), and the watcher package's internal goroutines.

### 1.2 Timers

| # | Timer | Interval | Go mechanism | Re-arm / cancel |
|---|-------|----------|--------------|-----------------|
| T1 | Heartbeat | 15s default (config.go:56, getter config.go:746) | `time.AfterFunc` heartbeat.go:42 inside `HeartbeatManager`: `mu` heartbeat.go:17 guards timer lifecycle; `generation atomic.Uint64` heartbeat.go:22 invalidates stale callbacks (bail-out heartbeat.go:44); `isRunning` callback re-checked at fire time heartbeat.go:44 | `Start` heartbeat.go:62-81, `Reset` heartbeat.go:86-104, `Stop` heartbeat.go:107-121; reset-on-data gates: run.go:444-448, workspace.go:862-868 |
| T2 | Wandb dir poll | 5s (workspacedirwatcher.go:17) | `tea.Tick` workspacedirwatcher.go:100-109 (scan runs inside tick callback) | re-armed by handler workspacedirwatcher.go:168-169 |
| T3 | Animation frames | 15ms (`AnimationFrame` = 150ms/10, styles.go:779-785) | `tea.Tick` at runhandlers.go:562, 752, 796; workspace.go:809, 816, 822, 828, 834, 840; rightsidebar.go:307; runoverviewsidebar.go:283 | each handler re-arms only while `IsAnimating()` (e.g. runhandlers.go:555-558); duration-based easing (animation.go:89-105), not frame-count-based |
| T4 | Symon sampling | 2s default (symonsampler.go:21) | `tea.Tick` symon.go:532-543 (sample runs inside tick cb, gated by `ctx.Done()` check); immediate pass symon.go:516-526 | re-armed after each processed sample (no overlap by construction) |
| T5 | File mtime poll | 500ms (core/internal/watcher/impl.go:29) | dedicated poller goroutines, see 1.7 | runs until `Finish()` |

### 1.3 Cross-goroutine shared state (locks and atomics)

| # | State | Site | Why it exists in Go |
|---|-------|------|---------------------|
| S1 | `Run.stateMu sync.RWMutex` | run.go:46; W-lock in `Update` run.go:202, `Cleanup` run.go:779; R-lock in `View` run.go:327, `MediaFullscreen` run.go:646 | Bubble Tea v2 may render `View` concurrently with `Update` |
| S2 | `Run.liveRunning atomic.Bool` | run.go:70; `isRunning` run.go:434-436; written on main goroutine only, `syncLiveRunning` run.go:451-453 | Read from heartbeat `AfterFunc` goroutine |
| S3 | `Workspace.hasLiveRuns atomic.Bool` | workspace.go:45; `syncLiveRunState` workspace.go:876-878 (main-goroutine-only writes, doc comment workspace.go:869-875); passed as `isRunning` at workspacehandlers.go:555, 697, 739, 767 | Same as S2 |
| S4 | `Run.animationMu sync.Mutex` + `animating bool` | run.go:96-97; `beginAnimating`/`endAnimating` runhandlers.go:359-375 | One-shot token; only ever touched from Update path |
| S5 | `LiveStore.mu sync.Mutex` | livestore.go:17 (Read/Close) | Reads happen on `tea.Cmd` goroutines that could overlap |
| S6 | `LevelDBHistorySource.mu sync.Mutex` | leveldbhistorysource.go:22 | Same as S5 |
| S7 | `AnimatedValue.mu sync.RWMutex` | animation.go:12 (all methods) | `Value()` read from View while Update mutates |
| S8 | `ConfigManager.mu sync.RWMutex` | config.go:158; sync `save()` via temp-file + rename config.go:335-353, called under lock | Getters callable from View / Cmd closures |
| S9 | `MetricsGrid.mu sync.RWMutex` | metricsgrid.go:23 | View-vs-Update |
| S10 | `MediaStore.mu sync.RWMutex` | media.go:32; store pointer shared between workspace and run views (run.go:167-170) | View-vs-Update + shared pointer |
| S11 | `mediaImageRenderer.mu sync.RWMutex` | mediapane.go:1167 | `PrepareVisible` mutates decode/render maps from a `tea.Cmd` goroutine |
| S12 | `Series.style atomic.Value` | epochlinechart.go:74 (design note epochlinechart.go:161-164) | Draw may run concurrently with `SetGraphStyle`/`SetPalette` |
| S13 | `darkBackground atomic.Bool` | styles.go:21-31 (written on `tea.BackgroundColorMsg`) | Package-global read during styling |
| S14 | `mediaKittyIDCounter atomic.Int64` | mediapane.go:55-59 | Process-wide Kitty image-ID namespace across panes |
| S15 | `symonsampler` local `mu sync.Mutex` | symonsampler.go:92, merge at :124-126 | Merges metric maps from parallel errgroup workers |
| S16 | `HeartbeatManager.mu` + `generation` | heartbeat.go:17, 22 | See T1 |

`sync.Once`: `termBgOnce` styles.go:48 (lazy terminal-bg query);
`configEditorFieldsOnce` configeditorfields.go:12 (lazy schema build);
`Workspace.autoSelectLatestRunOnLoad` workspace.go:56 (fired
workspacedirwatcher.go:180-181, main goroutine only);
`ParquetHistorySource.close sync.Once` parquethistorysource.go:72.

Contexts: `Run.initCancel` run.go:74, created run.go:183-184, cancelled in
cleanup runhandlers.go:340-343; `ParquetHistorySource.ctx/cancel`
parquethistorysource.go:70-71 (abort in-flight remote reads);
`Symon.ctx` symon.go:40-41, 69 (gates sampling ticks symon.go:518-524).

### 1.4 Backpressure and coalescing

| # | Pattern | Site |
|---|---------|------|
| B1 | Chunked reads bounded by count AND wall time: boot 1000 recs / 100ms, live 2000 recs / 50ms | historysource.go:13-21; `HistorySource.Read` contract historysource.go:32-46; `readChunkCmd` runhandlers.go:801-818; `ReadLiveBatchCmd` runhandlers.go:820-844; workspace `readAllChunkCmd` workspacehandlers.go:459-483, `ReadAvailableCmd` workspacehandlers.go:486-516 |
| B2 | Read chaining: next read issued only after previous batch handled | runhandlers.go:879-912 (boot), 915-926 (live); workspacehandlers.go:655-676 |
| B3 | `suppressDraw` — one chart redraw per batch, not per record | run.go:105; runhandlers.go:847-865 (set :852-853, single `drawVisible` :860-862); guard runhandlers.go:102; workspace equivalent: single `drawVisible` per batch workspacehandlers.go:664-665 |
| B4 | Bounded preloader, `maxConcurrentPreloads = 4` | workspacedirwatcher.go:28; FIFO+dedupe queue workspacedirwatcher.go:33-98. LOCK-FREE: state owned by the Update goroutine, concurrency achieved by counting in-flight `tea.Cmd`s |
| B5 | cap-1 coalescers | C3, C5 above |
| B6 | Heartbeat as safety net, reset on real data | T1 re-arm gates |

### 1.5 Panic handling

| # | Pattern | Site |
|---|---------|------|
| P1 | `logPanic`: log + stack trace, then re-panic (Bubble Tea's recover restores the terminal) | run.go:421-429; deferred in `Update` run.go:200, `View` run.go:325, `processRecordMsg` runhandlers.go:14 |
| P2 | `errgroup` + per-goroutine `recover` in sampler workers ("bubbletea's panic recovery does not cover goroutines spawned by commands") | symonsampler.go:92-131, recover at :100-106 |

### 1.6 Shutdown / cleanup

- `Model.Cleanup` model.go:270-277 → `Run.Cleanup` run.go:778-783 →
  `Run.cleanup` runhandlers.go:333-347, ORDER: heartbeat `Stop` → watcher
  `Finish` → `initCancel()` → `historySource.Close()`.
- `Workspace.Cleanup` workspace.go:356-369: heartbeat `Stop` → per-run
  `stopWatcher` (workspacehandlers.go:587-593) + `Reader.Close()`.
- Quit paths call cleanup themselves: runhandlers.go:349-354,
  workspacehandlers.go:773-778. Run→workspace transition: model.go:427.
- Symon: `Symon.Cleanup` symon.go:182 (cancel ctx + sampler cleanup), called by
  `runSymon` core/cmd/wandb-core/main.go:492.
- **GO BUG (do not port):** the `runLeetWorkspace` restart loop
  core/cmd/wandb-core/main.go:505-532 never calls `m.Cleanup()` before
  constructing a new `Model` on `ShouldRestart()` (main.go:527) — leaked
  watcher goroutines, heartbeat timer, and open readers per alt+r restart.
  Contrast `runSymon` main.go:492 which does clean up. Rust `Drop` fixes this
  for free (§2.9).
- Go also leaks the C5 prepare-pump goroutine (prepareCh is never closed). In
  Rust the pump unblocks via sender disconnect when the pane drops.

### 1.7 The watcher package (port verbatim)

`core/internal/watcher` wraps `radovskyb/watcher` (mtime polling):
500ms default poll (impl.go:29), Write|Create ops indistinguishable due to an
upstream race (impl.go:93-99), rapid same-mtime writes may emit nothing
(watcher.go:12-24 caveat), non-recursive `WatchDir`. Internals: two errgroup
goroutines + WaitGroup (impl.go:101-120), start-guarantee handshake
(impl.go:122-138), event loop impl.go:147-175, handler dispatch under mutex
impl.go:177-191, `Finish` closes and waits impl.go:71-83. Port the polling
semantics (mtime+size compare per registered path, 500ms) — **do not use the
notify crate**.

---

## 2. Target Rust design (normative — do not deviate)

### 2.1 Single event loop

One thread owns `Model` exclusively (`&mut`, no `Arc`, no locks). One
`std::sync::mpsc::channel::<Event>()`; the `Sender<Event>` is cloned to every
producer. Loop body: `recv()` → `model.update(event) -> Vec<Command>` →
dispatch commands → `terminal.draw(|f| model.view(f))`. `View` therefore runs
on the SAME thread as update.

### 2.2 Event enum

Mirror messages.go 1:1 — one variant per Go msg type, same payloads:
`History` (:17), `Run` (:24), `Summary` (:35), `SystemInfo` (:41),
`FileChanged` (:47), `FileComplete` (:50), `Stats` (:55), `ConsoleLog` (:63),
`Error` (:71), `Init` (:76), `BatchedRecords` (:81), `ChunkedBatch` (:86),
`Heartbeat` (:95), the 11 animation msgs (:98, :101, :104, :107, :164, :167,
:170, :173, :176, :179, :182), `WorkspaceRunInit` (:110),
`WorkspaceChunkedBatch` (:117), `WorkspaceBatchedRecords` (:123),
`WorkspaceFileChanged` (:132), `WorkspaceRunDirs` (:141),
`WorkspaceRunOverviewPreloaded` (:149), `WorkspaceInitErr` (:157), plus
`mediaPanePrepareMsg` mediapane.go:248-251. Add runtime variants:
`Input(crossterm::event::Event)` (replaces `tea.KeyPressMsg`/`MouseMsg`/
`WindowSizeMsg`), `Timer(TimerId)`, `ThreadPanicked { thread, message }`.

### 2.3 Producer threads

| Thread | Owns | Input | Output |
|--------|------|-------|--------|
| Input | crossterm | blocking `event::read()` loop | `Event::Input` |
| Reader (one per open `.wandb` / remote source) | the transaction-log or parquet reader, exclusively | `mpsc::Receiver<ReadRequest { chunk_size, max_time }>` (mirrors historysource.go:39-42) | `Event::ChunkedBatch` / `Event::WorkspaceChunkedBatch { run_key, .. }` |
| Watcher (singleton) | registered `path -> (mtime, size)` map; 500ms poll (§1.7) | register/unregister via its command channel | on change: `try_send(())` into that registration's crossbeam `bounded(1)` |
| Scheduler (singleton) | all timers (§2.4) | `mpsc::Receiver<TimerCmd>` | `Event::Timer(id)` |
| Effect threads | nothing persistent | one `Command` each (§2.7) | one `Event`, then exit |

Reader-thread ownership deletes S5/S6: Go's mutexes serialized overlapping
read-Cmds; a single-threaded reader with a request queue is the same
serialization. Requests are issued exactly where Go issues read Cmds (B2
chaining preserved).

### 2.4 Scheduler thread (single timer wheel — the ONLY timer approach)

```rust
enum TimerId { Heartbeat, DirPoll, SymonSample, Anim(AnimTarget) } // AnimTarget = 11 variants, one per animation msg
enum TimerCmd { Arm(TimerId, Duration), Cancel(TimerId) }
```

Loop: `recv_timeout(next_deadline)`; on `TimerCmd` mutate the
`HashMap<TimerId, Instant>`; on timeout, fire due entries (send
`Event::Timer(id)`, remove entry). `Arm` REPLACES any existing entry for that
id. All Go timers here are one-shot-rearmed-by-handler, which maps directly.

Why the heartbeat generation dance dies: in Go, `timer.Stop()` is best-effort —
an `AfterFunc` callback may already be executing, hence
`generation.Load() != gen` (heartbeat.go:44) plus the `isRunning()` re-check.
In Rust the scheduler is single-threaded: Arm/Cancel/fire are totally ordered
inside one thread, so a replaced or cancelled timer literally cannot fire.
The only residual race — a `Timer` event already sitting in the main queue when
the main thread changes state — is handled by the state checks Go ALREADY
performs on the main goroutine (`runState != Running` runhandlers.go:931-934,
`!anyRunRunning()` workspacehandlers.go:733-736, `IsAnimating()`
runhandlers.go:555-558). Port those checks; delete `generation`,
`HeartbeatManager.mu`, the `isRunning` callbacks, and S2/S3 atomics (liveness
is plain model state read on the main thread).

Concurrent same-type animation toggles: Go could briefly run two tick chains;
`Arm`-replace yields exactly one. Animations are wall-clock-eased
(animation.go:89-105), so timing is identical — accepted improvement.

### 2.5 Coalescing (C3/C5 replacement)

Use **crossbeam-channel `bounded(1)` + `try_send`** for every watcher
registration (workspace per-run AND single-run mode — the single-run 4096
buffer only ever queued redundant `FileChanged`s that trigger empty drains;
cap-1 is observably equivalent because every read drains all available data).
Note the dependency addition: `crossbeam-channel` (std `sync_channel(1)` has
`try_send` too, but crossbeam is prescribed for uniform disconnect semantics
with the pump commands; do not bikeshed this). C5 (media prepare) becomes a
plain `prepare_requested: bool` on the pane — in Rust the request originates on
the main thread (render path), so no channel is needed; handler clears the flag
and emits the prepare command, preserving cap-1 coalescing.

The pump (`WaitForMsg`) maps to `Command::AwaitWatcher { run_key }`: an effect
thread does ONE `recv()` on the run's bounded(1) receiver, sends
`Event::FileChanged`/`Event::WorkspaceFileChanged`, exits. The handler
re-issues the command exactly where Go re-arms (runhandlers.go:908/938/950,
workspacehandlers.go:549/761). Unregistering drops the registration's Sender →
`recv()` returns `Err(Disconnected)` → pump exits silently. This replaces the
C4 nil-send hack; there is no nil event.

C1/C2 disappear entirely: heartbeats go scheduler→main channel directly; file
changes go through the bounded(1)+pump. The main mpsc channel is the merge
point Bubble Tea's shared chans emulated.

### 2.6 Locks and atomics that DIE (delete; do not port)

| Go | Why it dies |
|----|-------------|
| S1 `Run.stateMu` | update and draw share one thread |
| S2/S3 liveness atomics | §2.4; plain `run_state` field checked on main thread |
| S4 `animationMu` | already main-thread-only in Go; plain `bool` |
| S5/S6 reader mutexes | reader-thread ownership (§2.3) |
| S7 `AnimatedValue.mu` | plain struct; only main thread animates/reads |
| S9 `MetricsGrid.mu` | main-thread-only |
| S10 `MediaStore.mu` | main-thread-only; the shared pointer becomes `Rc<RefCell<MediaStore>>` (run.go:167-170 sharing) |
| S11 renderer mutex | image DECODE runs as a `Command` on an effect thread returning `Event` with the decoded/encoded result; renderer maps live on the main thread |
| S12 `Series.style` atomic | plain field; draw is main-thread |
| S15 sampler merge mutex | `std::thread::scope` workers return partial maps; merge after join |
| S16 heartbeat mu+generation | §2.4 |
| `autoSelectLatestRunOnLoad` Once | plain `bool` field (main-thread) |
| parquet `close sync.Once` | `Option::take` in an idempotent `close()` |

Kept (as statics — Rust statics must be `Sync`, not because of real
cross-thread traffic): S13 → `static AtomicBool` (Relaxed), S14 →
`static AtomicI64`. `termBgOnce` → `OnceLock`; `configEditorFieldsOnce` →
`LazyLock<Vec<ConfigField>>`.

S8 `ConfigManager`: NO interior mutability. All reads and writes happen on the
main thread (they already do in Go — every setter is called from Update
handlers). `save()` stays synchronous on the main thread: it is a tiny JSON
temp-write + rename (config.go:335-353), triggered only by user keypresses. Do
not add a save thread.

### 2.7 Commands (tea.Cmd replacement)

`enum Command` executed by the effect runner; each blocking command runs on a
fresh `std::thread::spawn` (the mechanical goroutine equivalent; in-flight
count is bounded by B2/B4/§2.5 exactly as in Go) and sends exactly one `Event`.
Variants: `ReadChunk`/`ReadLive` (route to reader thread's request queue, not a
spawned thread), `AwaitWatcher`, `InitReader`, `PreloadRunOverview`,
`SampleSymon`, `PrepareMedia`, `Quit`. `tea.Tick` call sites become
`TimerCmd::Arm` sends to the scheduler — never spawned threads. Go's
consumed-key marker Cmd (`func() tea.Msg { return nil }` runhandlers.go:625)
becomes returning no command.

### 2.8 Panic policy

- `std::panic::set_hook`: restore terminal (leave alt screen, disable raw mode
  + mouse capture, show cursor), write panic + backtrace to the log file, then
  invoke the previous hook. This is P1's contract (log, then let the terminal
  be restored) without re-panicking games.
- Every producer/effect thread wraps its body in
  `catch_unwind(AssertUnwindSafe(..))`; on unwind it sends
  `Event::ThreadPanicked { thread, message }` — a panicking reader/watcher must
  NEVER die silently. Main loop logs it (CaptureError-equivalent) and degrades:
  mark the affected run's live streaming stopped; do not exit.
- Symon sampler workers `catch_unwind` per resource and skip that sample,
  mirroring symonsampler.go:100-106.
- Keep `panic = "unwind"` (default). Never `panic = "abort"`.

### 2.9 Shutdown → Drop

Implement explicit `Drop` (do not rely on struct field order) mirroring the Go
cleanup ordering:

- `impl Drop for Run` — mirror runhandlers.go:333-347: (1) send
  `TimerCmd::Cancel(Heartbeat)`; (2) unregister watcher path (drops the
  bounded(1) Sender → pump unblocks and exits, replacing C4); (3) cancel
  in-flight init (drop/flag the cancellation token — Go's `initCancel`
  run.go:74); (4) drop the reader request Sender → reader thread closes the
  file and exits (Go's `historySource.Close()`).
- `impl Drop for Workspace` — mirror workspace.go:356-369: cancel heartbeat,
  then per-run unregister + drop reader sender.
- `Model` drops its children; the quit/restart/exit-run-view paths
  (runhandlers.go:349-354, workspacehandlers.go:773-778, model.go:427) become
  ordinary drops/`Option::take`.
- Restart loop: `loop { let mut model = Model::new(..); run(&mut model)?; if
  !model.should_restart() { break } }` — the model drops at end of iteration,
  fixing the Go leak in main.go:505-532 (§1.6) for free. Symon restart
  (main.go:483-503) gets the same shape.

---

## 3. Mapping table (law)

| Go construct | Rust construct | Rule |
|--------------|----------------|------|
| goroutine + chan | thread + `std::sync::mpsc` | producers get a cloned `Sender<Event>`; model never leaves the loop thread |
| `tea.Msg` | `Event` enum variant | 1:1 with messages.go (§2.2) |
| `tea.Cmd` | `Command` enum, executed by effect runner | blocking work off-thread; result is exactly one `Event` (§2.7) |
| `tea.Batch(...)` | `Vec<Command>` | update returns all commands; loop dispatches in order |
| `tea.Tick(d, f)` | `TimerCmd::Arm(TimerId, d)` | scheduler thread owns ALL timers; no per-tick threads (§2.4) |
| `time.AfterFunc` + generation atomic + best-effort `Stop` | scheduler `Arm`(replace)/`Cancel` + main-thread state check on delivery | generation counters die (§2.4) |
| `select { case ch <- x: default: }` (drop) | `crossbeam bounded(1).try_send` (watcher) / direct unbounded send (heartbeat→main) | main channel is unbounded, producers never block |
| blocking pump Cmd (`WaitForMsg`, `waitForLiveMsg`, `waitForPrepare`) | `Command::Await*` — one `recv()` per issue, re-armed by handler | preserves one-in-flight delivery (§2.5) |
| nil-send to unblock pump (watchermanager.go:70-74) | drop the `Sender`; pump sees `Err(Disconnected)` and exits | no nil events exist |
| cap-4096 merge chans (run.go:124, workspace.go:135) | deleted; main mpsc channel is the merge point | §2.5 |
| `sync.Mutex`/`RWMutex` on model/UI state (S1,S4,S7,S9,S10,S11) | deleted (single-threaded ownership); shared stores → `Rc<RefCell<_>>` | §2.6 |
| `sync.Mutex` on reader (S5,S6) | reader-thread exclusive ownership + request queue | §2.3 |
| `atomic.Bool` read by timer callback (S2,S3) | plain model field; scheduler owns cancellation | §2.4 |
| `atomic.Value` style (S12) | plain field | §2.6 |
| package-global atomics (S13,S14) | `static AtomicBool` / `static AtomicI64` | statics must be `Sync`; Relaxed ordering |
| `sync.Once` (global) | `OnceLock` / `LazyLock` | §2.6 |
| `sync.Once` (per-instance, main-thread) | plain `bool` / `Option::take` | §2.6 |
| `errgroup` + per-goroutine `recover` (P2) | `std::thread::scope` + `catch_unwind` per worker; merge results after join | §2.8; S15 mutex dies |
| `context.WithCancel` | drop request `Sender` (readers) or `Arc<AtomicBool>` cancel flag checked at chunk boundaries (remote/parquet, symon) | cancellation observed at the same points Go checks `ctx.Done()` |
| `logPanic` + Bubble Tea recover (P1) | panic hook restoring terminal + `Event::ThreadPanicked` from threads | §2.8 |
| `Cleanup()` call chains (§1.6) | `impl Drop` with explicit ordered teardown | §2.9; fixes main.go:505 restart leak |
| `tea.Quit` | `Command::Quit` → loop breaks; model drops | §2.9 |
| `suppressDraw` batching (B3) | keep the same plain `bool`; ratatui additionally draws once per loop iteration | mechanical port |
| bounded preloader (B4) | port as-is: plain struct on the model, in-flight counted via issued `Command`s | already lock-free in Go |
| `radovskyb/watcher` mtime polling | hand-rolled 500ms poll loop in the watcher thread; Write/Create indistinguishable; same-mtime writes may be missed | §1.7 — NO notify crate |
