//! The Bubble Tea replacement (docs/CONCURRENCY.md §2): one event loop owns
//! the model; everything else is a producer that sends events into a single
//! `std::sync::mpsc` channel.
//!
//! Thread inventory (§2.3):
//!
//! | Thread        | Owns                          | Output                     |
//! |---------------|-------------------------------|----------------------------|
//! | main loop     | the [`App`] + the terminal    | draws; dispatches commands |
//! | input (process-singleton) | crossterm `event::read()` | `Event::Key/Mouse/Resize` |
//! | scheduler     | ALL timers (§2.4)             | `RuntimeEvent::Tick`       |
//! | reader (per source) | the `HistorySource`     | record events              |
//! | effect (one-shot)   | nothing persistent      | one event, then exit       |
//!
//! The input thread is a process singleton surviving the alt+r restart loop
//! (§2.9); each session installs its own sender (see [`spawn_input_thread`]).
//!
//! (The watcher singleton — the 500ms mtime poller, §1.7 — lives in
//! watcher_manager.rs; this module only runs its pump commands.)
//!
//! DIVERGENCE(CONCURRENCY.md §2.2): the doc adds `Timer`/`ThreadPanicked`
//! variants to the Event enum; the port wraps them in the runtime-level
//! [`RuntimeEvent`] envelope instead so [`Event`] stays 1:1 with messages.go
//! — every `Event` variant has a Go `%T` ack name, and `Timer`/
//! `ThreadPanicked` never reach `Update` (timer fires are translated to the
//! message the Go `tea.Tick` callback returns before delivery; a reader
//! thread's panic is delivered as the `ErrorMsg` its failed read would have
//! produced, see [`RuntimeEvent::ThreadPanicked`]).

use std::cell::Cell;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::{self, Read as _, Write};
use std::panic::{self, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, Once, OnceLock, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use crossterm::event::{
    DisableMouseCapture, EnableMouseCapture, Event as CtEvent, KeyboardEnhancementFlags,
    PopKeyboardEnhancementFlags, PushKeyboardEnhancementFlags,
};
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, SetTitle, disable_raw_mode, enable_raw_mode,
};
use crossterm::{cursor, execute};
use leet_charts::styles::Rgb;
use leet_data::history_source::{
    self as hs, BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME, HistorySource, LIVE_MONITOR_CHUNK_SIZE,
    LIVE_MONITOR_MAX_TIME, SourceMsg,
};
use leet_data::leveldb_history_source::LevelDBHistorySource;
use leet_data::test_mode;
use ratatui::Terminal;
use ratatui::backend::{Backend, CrosstermBackend};
use ratatui::layout::Size;
use ratatui::text::Text;

use crate::command::{
    Command, ReadKind, ReadRequest, SourceId, TimerId, execute_read, run_msg_to_event,
};
use crate::event::{
    ErrorMsg, Event, EventError, EventErrorKind, HistorySourceHandle, InitMsg, KittyGraphicsMsg,
    WorkspaceFileChangedMsg, WorkspaceInitErrMsg, WorkspaceRunDirsMsg, WorkspaceRunInitMsg,
    WorkspaceRunOverviewPreloadedMsg,
};
use crate::picture::{KittyCapability, PictureCmd, force_kitty_capability, kitty_supported};

// ---------------------------------------------------------------------------
// App trait — model.go's tea.Model surface
// ---------------------------------------------------------------------------

/// The surface the runtime drives; Phase 5b implements it for `Model`.
pub trait App {
    /// `tea.Model.Init` (model.go:124): the initial command batch.
    fn init(&mut self) -> Vec<Command>;

    /// `tea.Model.Update` (model.go:150): handle one event, return the
    /// command batch (`tea.Batch` → `Vec<Command>`, order preserved).
    fn update(&mut self, event: Event) -> Vec<Command>;

    /// `tea.Model.View` (model.go:236): the full-screen text block
    /// (`lipgloss.Place` already pads it to `size`); the runtime blits it
    /// into the ratatui frame buffer.
    ///
    /// `&mut self` where Go is a value receiver: Go's View mutates render
    /// bookkeeping under `stateMu` (CONCURRENCY.md S1); update and view
    /// share one thread here, so the lock is a plain mutable borrow.
    fn view(&mut self, size: Size) -> Text<'static>;

    /// The terminal window title. Go sets it on every rendered view value —
    /// model.go:253 (`"wandb leet"`), symon.go:175 (`"wandb leet symon"`) —
    /// but it is constant per model, so the runtime applies it once in
    /// [`setup_terminal`].
    fn window_title(&self) -> &str;

    /// Drains commands recorded during the draw that just completed — the
    /// same-thread replacement for Go's cap-1 media prepare channel, whose
    /// `waitForPrepare` pump wakes the event loop with `mediaPanePrepareMsg`
    /// right after the render WITHOUT further input (mediapane.go:213-231,
    /// CONCURRENCY.md §2.5 C5). The runtime calls this after every draw and
    /// dispatches the result; deferring it to the next update would leave a
    /// lone `k` (Kitty toggle) unrendered until another event arrived.
    fn after_draw(&mut self) -> Vec<Command> {
        Vec::new()
    }

    /// `Model.ShouldRestart` (model.go:260): read by the caller's restart
    /// loop after [`run`] returns (§2.9).
    fn should_restart(&self) -> bool;

    /// `Model.Cleanup` (model.go:270). Called when the loop exits — Go's
    /// quit paths run their own cleanup first (§1.6) and Cleanup is
    /// idempotent; calling it here also fixes the Go restart-loop leak
    /// (main.go:505-532, §2.9).
    fn cleanup(&mut self);
}

// ---------------------------------------------------------------------------
// Runtime event envelope
// ---------------------------------------------------------------------------

/// What travels on the main channel: app events plus the two runtime-only
/// signals (see the module-level DIVERGENCE note).
#[derive(Debug)]
pub enum RuntimeEvent {
    /// A message for `App::update`.
    App(Event),
    /// A scheduler fire (§2.4). Translated before delivery: animation and
    /// heartbeat ticks become their Go messages; `DirPoll` runs the dir
    /// scan effect (the Go tick callback body, workspacedirwatcher.go:105).
    Tick(TimerId),
    /// §2.8: a producer/effect thread panicked. The loop logs it
    /// (CaptureError-equivalent) and degrades; it never exits. When the
    /// panicking thread was a reader (`source` is set) the degrade is
    /// model-visible: the reader's registration has already been dropped
    /// (see `SourceRegistration`) and the loop delivers the `ErrorMsg` the
    /// failed read would have produced — the run view stops its heartbeat
    /// and watcher on `ErrorMsg` (runhandlers.go:86-88), i.e. "mark the
    /// affected run's live streaming stopped".
    ThreadPanicked {
        thread: String,
        message: String,
        /// The reader registration the panic killed, when the thread was a
        /// reader (§2.3); `None` for pumps/effects/scheduler.
        source: Option<SourceId>,
    },
    /// The input thread died (read error or panic). Fatal for the session:
    /// under raw mode there is no SIGINT, so an app without input cannot
    /// even be quit. PARITY: Bubble Tea forwards input-reader errors to
    /// `Program.Run`, which returns the error; [`run_loop`] does the same
    /// (after `App::cleanup`, with the terminal restored by [`run`]).
    InputFailed { message: String },
}

// ---------------------------------------------------------------------------
// Scheduler thread (§2.4 — the ONLY timer approach)
// ---------------------------------------------------------------------------

/// Commands understood by the scheduler thread.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimerCmd {
    /// Arm REPLACES any existing entry for the id. This is why Go's
    /// heartbeat generation counter (heartbeat.go:22) dies: Arm/Cancel/fire
    /// are totally ordered inside one thread, so a replaced or cancelled
    /// timer literally cannot fire.
    Arm(TimerId, Duration),
    Cancel(TimerId),
}

/// Spawns the scheduler thread; it exits when the returned sender drops.
pub fn spawn_scheduler(events: Sender<RuntimeEvent>) -> Sender<TimerCmd> {
    let (tx, rx) = mpsc::channel();
    spawn_guarded("scheduler", events, move |events| {
        scheduler_loop(&rx, events);
    });
    tx
}

fn scheduler_loop(cmds: &Receiver<TimerCmd>, events: &Sender<RuntimeEvent>) {
    let mut pending: HashMap<TimerId, Instant> = HashMap::new();
    loop {
        // Fire everything due, in deadline order (TimerId order breaks
        // exact ties deterministically).
        let now = Instant::now();
        let mut due: Vec<(Instant, TimerId)> = pending
            .iter()
            .filter(|&(_, &at)| at <= now)
            .map(|(&id, &at)| (at, id))
            .collect();
        due.sort();
        for (_, id) in due {
            // All Go timers are one-shot-rearmed-by-handler; the entry is
            // removed on fire.
            pending.remove(&id);
            if events.send(RuntimeEvent::Tick(id)).is_err() {
                return;
            }
        }

        let cmd = match pending.values().min().copied() {
            Some(deadline) => {
                match cmds.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
                    Ok(cmd) => Some(cmd),
                    Err(RecvTimeoutError::Timeout) => None,
                    Err(RecvTimeoutError::Disconnected) => return,
                }
            }
            None => match cmds.recv() {
                Ok(cmd) => Some(cmd),
                Err(_) => return,
            },
        };
        match cmd {
            Some(TimerCmd::Arm(id, duration)) => {
                pending.insert(id, Instant::now() + duration);
            }
            Some(TimerCmd::Cancel(id)) => {
                pending.remove(&id);
            }
            None => {}
        }
    }
}

// ---------------------------------------------------------------------------
// Panic policy (§2.8)
// ---------------------------------------------------------------------------

thread_local! {
    /// True on threads whose panics are survivable (§2.8): their
    /// `catch_unwind` reports [`RuntimeEvent::ThreadPanicked`] (or
    /// [`RuntimeEvent::InputFailed`]) and the main loop keeps running, so
    /// the process-global panic hook must neither restore the terminal
    /// (cooked mode under a live event loop = garbage frames) nor let the
    /// default hook scribble the panic on stderr over the alt screen.
    static PANIC_SURVIVABLE: Cell<bool> = const { Cell::new(false) };
}

/// Spawns a named thread whose body is wrapped in `catch_unwind`; on unwind
/// it sends [`RuntimeEvent::ThreadPanicked`] — a panicking producer must
/// never die silently (§2.8).
fn spawn_guarded<F>(name: &str, events: Sender<RuntimeEvent>, body: F)
where
    F: FnOnce(&Sender<RuntimeEvent>) + Send + 'static,
{
    spawn_guarded_for_source(name, events, None, body);
}

/// [`spawn_guarded`] with a reader identity: `source` tags the panic report
/// with the registration the panic kills, so the loop can degrade that
/// run's live streaming (§2.8).
fn spawn_guarded_for_source<F>(
    name: &str,
    events: Sender<RuntimeEvent>,
    source: Option<SourceId>,
    body: F,
) where
    F: FnOnce(&Sender<RuntimeEvent>) + Send + 'static,
{
    let thread_name = name.to_string();
    let spawned = thread::Builder::new()
        .name(thread_name.clone())
        .spawn(move || {
            PANIC_SURVIVABLE.set(true);
            if let Err(payload) = panic::catch_unwind(AssertUnwindSafe(|| body(&events))) {
                let message = panic_message(payload.as_ref());
                let _ = events.send(RuntimeEvent::ThreadPanicked {
                    thread: thread_name,
                    message,
                    source,
                });
            }
        });
    if let Err(err) = spawned {
        tracing::error!(%err, name, "failed to spawn thread");
    }
}

fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = payload.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else {
        "unknown panic".to_string()
    }
}

/// §2.8 P1: on a non-survivable panic (the main loop thread or an unguarded
/// helper) restore the terminal, log the panic + backtrace, then chain to
/// the previous hook (Go: `logPanic` + Bubble Tea's recover restoring the
/// terminal).
///
/// Guarded producer/effect threads are survivable: the hook fires BEFORE
/// their `catch_unwind` regains control, so restoring here would disable
/// raw mode and leave the alt screen under a still-running main loop. For
/// them the hook only logs; [`spawn_guarded`]'s `catch_unwind` then reports
/// [`RuntimeEvent::ThreadPanicked`] and the session keeps drawing.
pub fn install_panic_hook() {
    static INSTALL: Once = Once::new();
    INSTALL.call_once(|| {
        let prev = panic::take_hook();
        panic::set_hook(Box::new(move |info| {
            let backtrace = std::backtrace::Backtrace::force_capture();
            // try_with: a panic during TLS teardown must not double-panic
            // inside the hook (that would abort); default to the safe
            // restore path.
            if PANIC_SURVIVABLE.try_with(Cell::get).unwrap_or(false) {
                tracing::error!(panic = %info, %backtrace, "guarded thread panicked; session continues");
                return;
            }
            restore_terminal();
            tracing::error!(panic = %info, %backtrace, "panic; terminal restored");
            prev(info);
        }));
    });
}

// ---------------------------------------------------------------------------
// Test-mode acks (core/internal/leet/testmode.go)
// ---------------------------------------------------------------------------

/// Writes the harness ack protocol: `u <seq> <msgType>` after every Update
/// and `v <seq>` after every completed draw — byte-identical to
/// testmode.go's `fmt.Fprintf(s.f, "u %d %T\n", ..)` / `"v %d\n"`.
///
/// PARITY: Go's `testAckState` is a process-global `sync.OnceValue` — one
/// FIFO handle and one `atomic.Int64` seq for the whole process, persisting
/// across the alt+r restart loop. [`AckWriter::from_env`] therefore hands
/// out handles to ONE shared state: a per-session seq reset would let stale
/// high-seq `v` lines already in the harness history satisfy
/// `await_view(seq >= n)` before the awaited frame renders.
#[derive(Clone)]
pub struct AckWriter {
    state: Arc<Mutex<AckState>>,
}

struct AckState {
    f: Box<dyn Write + Send>,
    /// seq orders Update acks; View acks carry the latest Update seq so the
    /// harness knows a frame reflecting that update has been rendered.
    seq: i64,
}

impl AckWriter {
    /// testmode.go `testAckState`: active only when `WANDB_LEET_TEST=1` and
    /// `LEET_TEST_ACK_FILE` names a pre-created FIFO (or file). The harness
    /// holds the FIFO's read end open, so the `O_WRONLY|O_APPEND` open
    /// cannot block (see leet/harness/leet-harness/src/ack.rs). Like Go's
    /// `sync.OnceValue`, the FIFO is opened once per process and every call
    /// returns a handle to the same state.
    pub fn from_env() -> Option<AckWriter> {
        static STATE: OnceLock<Option<Arc<Mutex<AckState>>>> = OnceLock::new();
        STATE
            .get_or_init(|| {
                if !test_mode::enabled() {
                    return None;
                }
                let path = std::env::var("LEET_TEST_ACK_FILE")
                    .ok()
                    .filter(|p| !p.is_empty())?;
                let f = OpenOptions::new().append(true).open(path).ok()?;
                Some(Arc::new(Mutex::new(AckState {
                    f: Box::new(f),
                    seq: 0,
                })))
            })
            .clone()
            .map(|state| AckWriter { state })
    }

    pub fn new(f: Box<dyn Write + Send>) -> AckWriter {
        AckWriter {
            state: Arc::new(Mutex::new(AckState { f, seq: 0 })),
        }
    }

    /// testmode.go `testAckUpdate`. `msg_type` is [`Event::ack_name`].
    pub fn ack_update(&mut self, msg_type: &str) {
        let mut state = lock_unpoisoned(&self.state);
        state.seq += 1;
        let seq = state.seq;
        let _ = writeln!(state.f, "u {seq} {msg_type}");
        let _ = state.f.flush();
    }

    /// testmode.go `testAckView`.
    pub fn ack_view(&mut self) {
        let mut state = lock_unpoisoned(&self.state);
        let seq = state.seq;
        let _ = writeln!(state.f, "v {seq}");
        let _ = state.f.flush();
    }
}

// ---------------------------------------------------------------------------
// Effect runner (§2.7) — executes Commands
// ---------------------------------------------------------------------------

/// How a reader-thread init replies (single-run vs workspace mode).
#[derive(Debug, Clone)]
enum ReaderInit {
    /// run.go:187 → `Event::Init` / `Event::Error`.
    SingleRun,
    /// workspacehandlers.go:440 → `Event::WorkspaceRunInit` /
    /// `Event::WorkspaceInitErr`.
    Workspace { run_key: String },
}

/// Reader request queues (§2.3), shared with the reader threads so each can
/// deregister itself on exit.
type SourceMap = Arc<Mutex<HashMap<SourceId, Sender<ReadRequest>>>>;

/// Removes a reader's [`SourceMap`] entry on EVERY thread exit — including a
/// panic unwinding into `spawn_guarded`'s `catch_unwind` (§2.8), which would
/// skip a cleanup tail. A stale entry would over-report
/// [`EffectRunner::source_count`] and turn later `send_read`s into
/// disconnected-send noise instead of the Go nil-source no-op.
struct SourceRegistration {
    sources: SourceMap,
    id: SourceId,
}

impl Drop for SourceRegistration {
    fn drop(&mut self) {
        lock_unpoisoned(&self.sources).remove(&self.id);
    }
}

/// Dispatches [`Command`]s: routes reads to reader threads, timer arms to
/// the scheduler, and runs one-shot blocking work on effect threads
/// (the mechanical goroutine equivalent; in-flight count is bounded by
/// B2/B4/§2.5 exactly as in Go).
pub struct EffectRunner {
    events: Sender<RuntimeEvent>,
    timers: Sender<TimerCmd>,
    /// Reader request queues (§2.3). Removing an entry drops the sender →
    /// the reader thread closes its file and exits (Go
    /// `historySource.Close()`).
    sources: SourceMap,
    next_source_id: u64,
    /// Stashed by [`Command::PollWandbDir`] for `DirPoll` fires (the Go
    /// tick callback captures `w.wandbDir`, workspacedirwatcher.go:101).
    wandb_dir: Option<String>,
    /// The terminal replies captured by the startup round-trip
    /// ([`detect_terminal_capabilities`]); all-empty in test mode.
    caps: TerminalCapabilities,
    /// Set by [`Command::Quit`]; the loop exits after the current batch.
    quit: bool,
}

impl EffectRunner {
    pub fn new(events: Sender<RuntimeEvent>, timers: Sender<TimerCmd>) -> EffectRunner {
        EffectRunner {
            events,
            timers,
            sources: Arc::new(Mutex::new(HashMap::new())),
            next_source_id: 1,
            wandb_dir: None,
            caps: TerminalCapabilities::default(),
            quit: false,
        }
    }

    pub fn quit_requested(&self) -> bool {
        self.quit
    }

    pub(crate) fn set_terminal_capabilities(&mut self, caps: TerminalCapabilities) {
        self.caps = caps;
    }

    /// Sends an event back through the main queue.
    pub fn emit(&self, event: Event) {
        let _ = self.events.send(RuntimeEvent::App(event));
    }

    pub fn dispatch(&mut self, command: Command) {
        match command {
            Command::RequestBackgroundColor => {
                // PARITY: tea.RequestBackgroundColor queries OSC 11 and
                // delivers tea.BackgroundColorMsg; the runtime performed the
                // round-trip once at startup (see detect_background_is_dark)
                // and replays the answer. No terminal reply → no message,
                // exactly like Go.
                if let Some(is_dark) = self.caps.background_is_dark {
                    self.emit(Event::BackgroundColor {
                        is_dark,
                        rgb: self.caps.background_rgb,
                    });
                }
            }
            Command::InitReader { run_path } => self.spawn_reader(run_path, ReaderInit::SingleRun),
            Command::InitRemoteReader { remote } => {
                // PHASE-7: parquethistorysource.go / leet-remote.
                tracing::warn!(?remote, "InitRemoteReader not yet ported (PHASE-7)");
            }
            Command::InitWorkspaceReader { run_key, run_path } => {
                self.spawn_reader(run_path, ReaderInit::Workspace { run_key });
            }
            Command::ReadChunk {
                source,
                chunk_size,
                max_time_per_chunk,
            } => self.send_read(
                source,
                ReadRequest {
                    kind: ReadKind::Chunk,
                    chunk_size,
                    max_time_per_chunk,
                },
            ),
            Command::ReadLiveBatch { source } => self.send_read(
                source,
                ReadRequest {
                    kind: ReadKind::LiveBatch,
                    chunk_size: LIVE_MONITOR_CHUNK_SIZE,
                    max_time_per_chunk: LIVE_MONITOR_MAX_TIME,
                },
            ),
            Command::ReadAllChunk { source, run_key } => self.send_read(
                source,
                ReadRequest {
                    kind: ReadKind::WorkspaceChunk { run_key },
                    chunk_size: BOOT_LOAD_CHUNK_SIZE,
                    max_time_per_chunk: BOOT_LOAD_MAX_TIME,
                },
            ),
            Command::ReadAvailable { source, run_key } => self.send_read(
                source,
                ReadRequest {
                    kind: ReadKind::WorkspaceAvailable { run_key },
                    chunk_size: LIVE_MONITOR_CHUNK_SIZE,
                    max_time_per_chunk: LIVE_MONITOR_MAX_TIME,
                },
            ),
            Command::CloseReader { source } => {
                // Dropping the sender ends the reader thread (§2.9).
                lock_unpoisoned(&self.sources).remove(&source);
            }
            Command::AwaitWatcherMsg { rx } => {
                spawn_guarded("watcher-pump", self.events.clone(), move |events| {
                    // One recv per issue (§2.5); Err = the watcher was
                    // unregistered — exit silently (replaces C4's nil-send).
                    if rx.recv().is_ok() {
                        let _ = events.send(RuntimeEvent::App(Event::FileChanged));
                    }
                });
            }
            Command::AwaitWorkspaceWatcher { run_key, rx } => {
                spawn_guarded("watcher-pump", self.events.clone(), move |events| {
                    if rx.recv().is_ok() {
                        let _ = events.send(RuntimeEvent::App(Event::WorkspaceFileChanged(
                            WorkspaceFileChangedMsg { run_key },
                        )));
                    }
                });
            }
            Command::Tick { id, duration } => {
                let _ = self.timers.send(TimerCmd::Arm(id, duration));
            }
            Command::CancelTimer { id } => {
                let _ = self.timers.send(TimerCmd::Cancel(id));
            }
            Command::PollWandbDir { wandb_dir, delay } => {
                self.wandb_dir = Some(wandb_dir);
                let _ = self.timers.send(TimerCmd::Arm(TimerId::DirPoll, delay));
            }
            Command::PreloadRunOverview {
                run_key,
                wandb_file,
            } => {
                spawn_guarded("overview-preload", self.events.clone(), move |events| {
                    let msg = preload_run_overview(&run_key, &wandb_file);
                    let _ =
                        events.send(RuntimeEvent::App(Event::WorkspaceRunOverviewPreloaded(msg)));
                });
            }
            Command::Emit(event) => self.emit(*event),
            Command::Picture(PictureCmd::Raw(seq)) => {
                // tea.Raw: bytes straight to the terminal (Kitty deletes).
                let mut out = io::stdout();
                let _ = out.write_all(seq.as_bytes());
                let _ = out.flush();
            }
            Command::Picture(PictureCmd::Render(request)) => {
                // renderCmd's deferred closure (picture.go:563-608) ran on
                // a tea.Cmd goroutine; the effect thread is its §2.7
                // equivalent. A None frame (prepareSource failure) sends
                // nothing — the Go closure returns nil.
                spawn_guarded("kitty-render", self.events.clone(), move |events| {
                    if let Some(frame) = request.run() {
                        let _ = events.send(RuntimeEvent::App(Event::KittyFrame(Box::new(frame))));
                    }
                });
            }
            Command::RequestCellSize => {
                // PARITY: picture.RequestCellSize() is `tea.Raw(CSI 16 t)`
                // (picture.go:485-492) and ultraviolet decodes the async
                // `CSI 6 ; h ; w t` reply into uv.CellSizeEvent. crossterm
                // cannot surface that reply (its parser errors on the final
                // 't' and drops the sequence), so the runtime wrote the
                // query during the startup round-trip — before the input
                // thread owned the tty — and replays the captured answer,
                // the RequestBackgroundColor pattern. No reply → no
                // message, exactly like a non-answering terminal in Go.
                if let Some((width, height)) = self.caps.cell_size {
                    self.emit(Event::CellSize { width, height });
                }
            }
            Command::QueryKittySupport => self.query_kitty_support(),
            Command::SampleSymonNow => {
                // PHASE-6: symon sampler.
                tracing::debug!("symon sampling not yet ported (PHASE-6)");
            }
            Command::Quit => self.quit = true,
        }
    }

    /// The number of live reader registrations (test hook).
    pub fn source_count(&self) -> usize {
        lock_unpoisoned(&self.sources).len()
    }

    /// Spawns the thread that owns one `.wandb` reader: open on-thread (the
    /// Go init cmd body), announce, then serve read requests until the
    /// request sender drops (§2.3; the request queue is Go's S5/S6 reader
    /// mutex).
    fn spawn_reader(&mut self, run_path: String, init: ReaderInit) {
        let id = SourceId(self.next_source_id);
        self.next_source_id += 1;
        let sources = Arc::clone(&self.sources);
        spawn_guarded_for_source(
            &format!("reader-{}", id.0),
            self.events.clone(),
            Some(id),
            move |events| {
                let mut source = match LevelDBHistorySource::new(&run_path) {
                    Ok(source) => source,
                    Err(err) => {
                        let event = match init {
                            // PARITY: Go's exact error string
                            // (leveldbhistorysource.go:60-64).
                            ReaderInit::SingleRun => Event::Error(ErrorMsg {
                                err: EventError::other(format!(
                                    "leveldbhistory: failed to create live store: {err}"
                                )),
                            }),
                            ReaderInit::Workspace { run_key } => {
                                Event::WorkspaceInitErr(WorkspaceInitErrMsg {
                                    run_key,
                                    run_path: run_path.clone(),
                                    err: Some(EventError::new(
                                        classify_error(&err),
                                        err.to_string(),
                                    )),
                                })
                            }
                        };
                        let _ = events.send(RuntimeEvent::App(event));
                        return;
                    }
                };

                let (request_tx, request_rx) = mpsc::channel::<ReadRequest>();
                lock_unpoisoned(&sources).insert(id, request_tx);
                // Deregisters on drop — normal exit AND panic unwind.
                let _registration = SourceRegistration { sources, id };
                let handle = HistorySourceHandle { id };
                let event = match init {
                    ReaderInit::SingleRun => Event::Init(InitMsg { source: handle }),
                    ReaderInit::Workspace { run_key } => {
                        Event::WorkspaceRunInit(WorkspaceRunInitMsg {
                            run_key,
                            run_path: run_path.clone(),
                            reader: handle,
                        })
                    }
                };
                if events.send(RuntimeEvent::App(event)).is_ok() {
                    while let Ok(request) = request_rx.recv() {
                        if let Some(event) = execute_read(&mut source, request)
                            && events.send(RuntimeEvent::App(event)).is_err()
                        {
                            break;
                        }
                    }
                }
                // Request sender dropped (CloseReader / shutdown): Go's
                // historySource.Close(); `_registration` deregisters `id`.
                source.close();
            },
        );
    }

    fn send_read(&self, source: SourceId, request: ReadRequest) {
        // PARITY: Go's read cmds no-op on a nil source (runhandlers.go:803,
        // workspacehandlers.go:460); an unknown/closed id drops the same way.
        if let Some(tx) = lock_unpoisoned(&self.sources).get(&source)
            && tx.send(request).is_err()
        {
            tracing::debug!(?source, "read request to finished reader dropped");
        }
    }

    /// T2's tick-callback body: scan the wandb dir off-thread and report
    /// `WorkspaceRunDirsMsg` (workspacedirwatcher.go:105-108).
    fn spawn_dir_scan(&self) {
        let Some(wandb_dir) = self.wandb_dir.clone() else {
            return;
        };
        spawn_guarded("wandb-dir-scan", self.events.clone(), move |events| {
            let (run_keys, err) = scan_wandb_run_dirs(&wandb_dir);
            let _ = events.send(RuntimeEvent::App(Event::WorkspaceRunDirs(
                WorkspaceRunDirsMsg { run_keys, err },
            )));
        });
    }

    /// Port of `picture.QueryKittySupport` (kitty_capability.go:116-140).
    ///
    /// PARITY: Go's `kittyQueryOnce sync.Once` is process-wide — both media
    /// panes batch the query from Init and only the first emission does
    /// anything, and the guard survives the alt+r restart loop. The probe
    /// bytes themselves went to the wire during the startup round-trip
    /// ([`detect_terminal_capabilities`]), because crossterm's input parser
    /// cannot surface the APC response (it would decode as garbage key
    /// presses); this method replays the outcome through the same two
    /// messages Go uses (`uv.KittyGraphicsEvent` / `kittyProbeTickMsg`).
    fn query_kitty_support(&self) {
        static KITTY_QUERY_ONCE: AtomicBool = AtomicBool::new(false);
        if KITTY_QUERY_ONCE.swap(true, Ordering::SeqCst) {
            return;
        }
        let plan = plan_kitty_query(
            kitty_supported(),
            self.caps.kitty_probe_sent,
            self.caps.kitty_probe_responded,
        );
        self.run_kitty_query_plan(plan);
    }

    /// The effectful half of [`plan_kitty_query`] (split for testability —
    /// only `ResolveUnsupported` touches the process-wide capability).
    fn run_kitty_query_plan(&self, plan: KittyQueryPlan) {
        match plan {
            // Capability was already set (e.g. ForceKittyCapability before
            // any Init ran): respect that and skip (kitty_capability.go:121).
            KittyQueryPlan::Noop => {}
            KittyQueryPlan::ResolveUnsupported => {
                // Go: kittyCap.CompareAndSwap(Unknown, Unsupported)
                // (kitty_capability.go:128). Dispatch runs on the sole
                // update thread, so read + conditional store is that CAS.
                if kitty_supported() == KittyCapability::Unknown {
                    force_kitty_capability(KittyCapability::Unsupported);
                }
            }
            KittyQueryPlan::Await { responded } => {
                // Go batches tea.Raw(probe) + tea.Tick(kittyProbeTimeout)
                // (kitty_capability.go:132-137). The probe is already on
                // the wire; deliver the captured response (if any) and arm
                // the timeout tick regardless — a response is authoritative
                // and the late tick's recordKittyTimeout no-ops once the
                // capability is Supported (kitty_capability.go:190-211).
                if responded {
                    self.emit(Event::KittyGraphics(KittyGraphicsMsg {
                        id: KITTY_PROBE_ID,
                    }));
                }
                let _ = self
                    .timers
                    .send(TimerCmd::Arm(TimerId::KittyProbe, KITTY_PROBE_TIMEOUT));
            }
        }
    }
}

/// What executing [`Command::QueryKittySupport`] should do — the decision
/// half of `picture.QueryKittySupport` (kitty_capability.go:116-140),
/// separated from its process-global side effects for unit testing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum KittyQueryPlan {
    /// Capability already resolved before the query ran.
    Noop,
    /// Env preflight was negative: resolve straight to Unsupported without
    /// any messages (kitty_capability.go:126-130).
    ResolveUnsupported,
    /// The probe went to the wire: deliver the captured response (if any)
    /// and arm the probe-timeout tick.
    Await { responded: bool },
}

fn plan_kitty_query(
    current: KittyCapability,
    probe_sent: bool,
    probe_responded: bool,
) -> KittyQueryPlan {
    if current != KittyCapability::Unknown {
        return KittyQueryPlan::Noop;
    }
    if !probe_sent {
        return KittyQueryPlan::ResolveUnsupported;
    }
    KittyQueryPlan::Await {
        responded: probe_responded,
    }
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Producers classify errors for the two tests Go call sites perform:
/// `os.IsNotExist(err)` and `errors.Is(err, errRunRecordNotFound)`
/// (see [`EventError`]). Walks the source chain for an io NotFound.
fn classify_error(err: &(dyn std::error::Error + 'static)) -> EventErrorKind {
    let mut current: Option<&(dyn std::error::Error + 'static)> = Some(err);
    while let Some(e) = current {
        if let Some(io_err) = e.downcast_ref::<io::Error>()
            && io_err.kind() == io::ErrorKind::NotFound
        {
            return EventErrorKind::NotExist;
        }
        current = e.source();
    }
    EventErrorKind::Other
}

// ---------------------------------------------------------------------------
// Workspace-dir effects (the off-thread bodies of workspacedirwatcher.go's
// commands; the on-thread queue/handlers port with workspace_dir_watcher.rs)
// ---------------------------------------------------------------------------

/// workspacedirwatcher.go:22 `maxRecordsToScan`.
pub const MAX_RECORDS_TO_SCAN: usize = 10;
/// workspacedirwatcher.go:25 `maxRecordsToScanTimeout`.
pub const MAX_RECORDS_TO_SCAN_TIMEOUT: Duration = Duration::from_millis(100);
/// workspacedirwatcher.go:31 `errRunRecordNotFound`.
pub const ERR_RUN_RECORD_NOT_FOUND: &str = "run record not found";

/// Port of `scanWandbRunDirs` (workspacedirwatcher.go:111-140). Runs on the
/// dir-scan effect thread.
pub fn scan_wandb_run_dirs(wandb_dir: &str) -> (Vec<String>, Option<EventError>) {
    if wandb_dir.is_empty() {
        return (Vec::new(), None);
    }
    let entries = match std::fs::read_dir(wandb_dir) {
        Ok(entries) => entries,
        Err(err) => {
            let kind = if err.kind() == io::ErrorKind::NotFound {
                EventErrorKind::NotExist
            } else {
                EventErrorKind::Other
            };
            // PARITY: Go's *PathError renders "open <dir>: <errno text>".
            return (
                Vec::new(),
                Some(EventError::new(kind, format!("open {wandb_dir}: {err}"))),
            );
        }
    };

    let mut run_keys: Vec<String> = Vec::new();
    for entry in entries.flatten() {
        // PARITY: Go strings are raw bytes; a non-UTF-8 name cannot match
        // the run-/offline-run- prefixes and is skipped either way.
        let Some(name) = entry.file_name().to_str().map(String::from) else {
            continue;
        };
        if !name.starts_with("run-") && !name.starts_with("offline-run-") {
            continue;
        }
        run_keys.push(name);
    }

    // Sort by timestamp in descending order (most recent first); ties by
    // name ascending. Go's slices.SortFunc is unstable but the comparator
    // is total (names are unique within a directory), so a stable sort
    // yields the identical order.
    run_keys.sort_by(|a, b| {
        let (ta, tb) = (parse_run_dir_timestamp(a), parse_run_dir_timestamp(b));
        tb.cmp(&ta).then_with(|| a.cmp(b))
    });

    (run_keys, None)
}

/// Port of `parseRunDirTimestamp` (workspacedirwatcher.go:142-165).
///
/// Returns the validated 15-char `YYYYMMDD_HHMMSS` stamp — it compares
/// lexicographically exactly as the parsed `time.Time` compares — or `None`
/// for Go's zero time (parse failure), which sorts last in descending order.
pub fn parse_run_dir_timestamp(name: &str) -> Option<String> {
    let rest = name
        .strip_prefix("offline-run-")
        .or_else(|| name.strip_prefix("run-"))?;
    let stamp = rest.get(..15)?;
    let bytes = stamp.as_bytes();
    if bytes[8] != b'_'
        || !bytes
            .iter()
            .enumerate()
            .all(|(i, b)| i == 8 || b.is_ascii_digit())
    {
        return None;
    }
    // time.Parse("20060102_150405", ..) field validation.
    let field = |range: std::ops::Range<usize>| -> u32 {
        stamp[range].parse().expect("digits validated above")
    };
    let (year, month, day) = (field(0..4), field(4..6), field(6..8));
    let (hour, minute, second) = (field(9..11), field(11..13), field(13..15));
    if !(1..=12).contains(&month) || hour > 23 || minute > 59 || second > 59 {
        return None;
    }
    if day < 1 || day > days_in_month(year, month) {
        return None;
    }
    Some(stamp.to_string())
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            let leap =
                year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400));
            if leap { 29 } else { 28 }
        }
        _ => 0,
    }
}

/// Port of `preloadRunOverviewCmd`'s closure body
/// (workspacedirwatcher.go:230-256). Runs on a preload effect thread; B4's
/// bounded concurrency (max 4 in flight) is enforced by the model's
/// preloader queue issuing at most that many commands.
pub fn preload_run_overview(run_key: &str, wandb_file: &str) -> WorkspaceRunOverviewPreloadedMsg {
    let msg = |run, err| WorkspaceRunOverviewPreloadedMsg {
        run_key: run_key.to_string(),
        run,
        err,
    };
    let not_found = || {
        Some(EventError::new(
            EventErrorKind::RunRecordNotFound,
            ERR_RUN_RECORD_NOT_FOUND,
        ))
    };

    if run_key.is_empty() || wandb_file.is_empty() {
        return msg(None, not_found());
    }

    let mut reader = match LevelDBHistorySource::new(wandb_file) {
        Ok(reader) => reader,
        Err(err) => {
            return msg(
                None,
                Some(EventError::new(classify_error(&err), err.to_string())),
            );
        }
    };

    let (read_msg, err) = reader.read(MAX_RECORDS_TO_SCAN, MAX_RECORDS_TO_SCAN_TIMEOUT);
    let result = if let Some(err) = err.filter(|e| !e.is_eof()) {
        msg(
            None,
            Some(EventError::new(classify_error(&err), err.to_string())),
        )
    } else {
        match read_msg.and_then(find_run_msg) {
            Some(run) => msg(Some(Box::new(run_msg_to_event(run))), None),
            None => msg(None, not_found()),
        }
    };
    // Go: defer reader.Close().
    reader.close();
    result
}

/// Port of `FindRunMsg` (workspacedirwatcher.go:258-276): the first RunMsg
/// with a populated run ID, searching inside chunked batches.
// PARITY: Go's BatchedRecordsMsg arm is unreachable from
// HistorySource.Read (it never returns one); SourceMsg has no such variant.
pub fn find_run_msg(msg: SourceMsg) -> Option<hs::RunMsg> {
    match msg {
        SourceMsg::Run(run) => (!run.id.is_empty()).then_some(run),
        SourceMsg::ChunkedBatch(batch) => batch.msgs.into_iter().find_map(find_run_msg),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Terminal capability queries (runtime only — never in test mode)
// ---------------------------------------------------------------------------

/// PARITY: termenv's `OSCTimeout` (termenv_unix.go:18) — Go leet's
/// `initTerminalBg` blocks startup on its OSC 11 status report for up to 5s
/// of tty silence before rendering without it (measured: Go's first frame at
/// t=5.07s under a scripted PTY that never answers any query; a real
/// Ghostty answers within ~10ms and the DA1 fence ends the wait right
/// there). The window also decides who captures replies that arrive late
/// (slow ssh): within it they land in the round-trip buffer like Go's
/// termenv reader; after it they would reach crossterm's input thread,
/// whose ESC-fallback parser turns an OSC/APC reply into garbage key
/// presses (alt+']' plus the payload chars — digits toggle panes). Matching
/// Go's window makes the leak-free coverage identical to the oracle's.
const TERMINAL_QUERY_TIMEOUT: Duration = Duration::from_secs(5);

/// kitty_capability.go:43 `kittyProbeID` — the image ID used for the Kitty
/// support probe, far above any consumer-assigned ID.
pub(crate) const KITTY_PROBE_ID: i64 = 42069101;

/// kitty_capability.go:49 `kittyProbeTimeout`.
pub(crate) const KITTY_PROBE_TIMEOUT: Duration = Duration::from_millis(250);

/// `ansi.WindowOp(16)` — the XTWINOPS cell-pixel-size query emitted by
/// `picture.RequestCellSize()` (picture.go:490-492).
const CELL_SIZE_QUERY: &[u8] = b"\x1b[16t";

/// kitty_capability.go:177-183 `buildKittyQueryAPC`: a Kitty graphics query
/// (`a=q`) — a tiny 1×1 transmit whose only purpose is to elicit a
/// response. Kitty terminals reply `ESC _ G i=<id> ; OK ESC \`; non-Kitty
/// terminals don't reply. "AAAA" is base64 of three zero bytes (one RGB
/// pixel).
fn build_kitty_query_apc(id: i64) -> String {
    format!("\x1b_Ga=q,t=d,f=24,s=1,v=1,i={id};AAAA\x1b\\")
}

/// kitty_capability.go:147-175 `kittyEnvSignal`: the pre-flight gate — the
/// probe is only sent when the environment indicates a Kitty-aware terminal,
/// so non-Kitty terminals never see APC bytes they might print as garbage.
fn kitty_env_signal() -> bool {
    kitty_env_signal_from(|key| std::env::var(key).unwrap_or_default())
}

fn kitty_env_signal_from(getenv: impl Fn(&str) -> String) -> bool {
    if !getenv("KITTY_WINDOW_ID").is_empty() || !getenv("KITTY_INSTALLATION_DIR").is_empty() {
        return true;
    }
    if !getenv("GHOSTTY_RESOURCES_DIR").is_empty() {
        return true;
    }
    if !getenv("WEZTERM_EXECUTABLE").is_empty() || !getenv("WEZTERM_PANE").is_empty() {
        return true;
    }
    if matches!(getenv("TERM").as_str(), "xterm-kitty" | "xterm-ghostty") {
        return true;
    }
    // PARITY: exact, case-SENSITIVE matches (kitty_capability.go:166-174),
    // unlike mediapane.go's lowercased `terminalSignalsKittyGraphics`
    // (media_pane.rs `terminal_signals_kitty_graphics`) — the two gates
    // deliberately differ in Go too.
    matches!(
        getenv("TERM_PROGRAM").as_str(),
        "ghostty" | "WezTerm" | "kitty" | "iTerm.app"
    )
}

/// The replies captured by the startup terminal round-trip.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct TerminalCapabilities {
    /// OSC 11 background classification; `None` = no reply.
    pub(crate) background_is_dark: Option<bool>,
    /// The same OSC 11 reply as 8-bit RGB for the runs-list zebra stripe
    /// (Go reads it via termenv, styles.go `initTerminalBg`); `None` = no
    /// reply or a form termenv rejects (see [`parse_osc11_rgb`]).
    pub(crate) background_rgb: Option<Rgb>,
    /// CSI 16 t reply: the terminal's cell (width, height) in pixels.
    pub(crate) cell_size: Option<(isize, isize)>,
    /// Whether the Kitty `a=q` probe went to the wire (env preflight
    /// positive AND /dev/tty writable).
    pub(crate) kitty_probe_sent: bool,
    /// Whether the terminal answered the probe.
    pub(crate) kitty_probe_responded: bool,
}

/// PARITY: mirrors the wire halves of `tea.RequestBackgroundColor`,
/// `picture.RequestCellSize` and `picture.QueryKittySupport` — Bubble Tea/
/// ultraviolet emit the queries and decode the async replies on the input
/// path. The
/// port performs ONE round-trip at startup, before the crossterm input
/// thread owns the tty: crossterm-0.29 has no passthrough for these replies
/// (the OSC 11 and `CSI 6;h;w t` replies error out of its parser and are
/// dropped; the Kitty APC response would decode as garbage key presses via
/// its ESC-prefix alt-key fallback). A DA1 (`CSI c`) fence follows the
/// queries: terminals answer in order, so once DA1 arrives every earlier
/// reply has too, bounding the read. No reply within the timeout → the
/// corresponding capability stays empty, exactly like a non-answering
/// terminal in Go.
///
/// In test mode this is never called: there are NO terminal queries; the
/// background is forced dark (light via `WANDB_LEET_TEST_BG=light`) through
/// `leet_charts::styles::default_dark_background()` (testmode.go) and the
/// media pane suppresses its capability queries (mediapane.go:180-184).
pub(crate) fn detect_terminal_capabilities(timeout: Duration) -> TerminalCapabilities {
    let probe = kitty_env_signal();
    let mut query: Vec<u8> = b"\x1b]11;?\x07".to_vec();
    query.extend_from_slice(CELL_SIZE_QUERY);
    if probe {
        query.extend_from_slice(build_kitty_query_apc(KITTY_PROBE_ID).as_bytes());
    }
    query.extend_from_slice(b"\x1b[c");

    let Some(buf) = terminal_round_trip(&query, timeout) else {
        // /dev/tty unavailable: nothing was written, so the probe was
        // never sent either.
        return TerminalCapabilities::default();
    };
    TerminalCapabilities {
        background_is_dark: parse_osc11_is_dark(&buf),
        background_rgb: parse_osc11_rgb(&buf),
        cell_size: parse_cell_size_reply(&buf),
        kitty_probe_sent: probe,
        kitty_probe_responded: probe && contains_kitty_probe_response(&buf, KITTY_PROBE_ID),
    }
}

/// Writes `query` to /dev/tty and reads the reply until the DA1 fence, the
/// deadline, or EOF/error. `None` = the tty could not be opened/written.
///
/// Single-threaded and deadline-bounded — but NOT by `poll(2)`: on macOS,
/// poll on a /dev/tty fd fails immediately with POLLNVAL in `revents`
/// (measured: revents=32 after 0ms under a scripted PTY), so its verdict is
/// advisory at best and a blocking read behind it hung startup forever on a
/// terminal that never answers the DA1 fence. The bound is carried by the
/// O_NONBLOCK fd + the explicit deadline check at the top of the loop; the
/// poll is kept for platforms where it works (it sleeps instead of the
/// 10ms retry pacing). (An earlier design parked a byte-reader thread on
/// the fd past the timeout; a DA1 reply arriving late — slow ssh — then ate
/// user keystrokes until it landed, and a terminal that never answered had
/// one future byte stolen from the crossterm input thread that takes over
/// next.)
///
/// Bytes typed while the round-trip is pending are consumed into `buf` and
/// dropped with it — Go loses them the same way (termenv's
/// `readNextResponse` eats non-ESC bytes while hunting for its reply, and
/// even restarts its 5s silence window on every byte; this deadline is
/// absolute).
#[cfg(unix)]
fn terminal_round_trip(query: &[u8], timeout: Duration) -> Option<Vec<u8>> {
    use rustix::event::{PollFd, PollFlags, Timespec};

    let mut tty = OpenOptions::new()
        .read(true)
        .write(true)
        .open("/dev/tty")
        .ok()?;
    // Non-blocking reads: on macOS, poll(2) on /dev/tty can report
    // readiness when no reply bytes exist, and the subsequent blocking
    // read(2) then parks the main thread FOREVER on a terminal that never
    // answers (observed empirically on Darwin 25 under a scripted PTY: a
    // no-reply "dumb" terminal hung boot inside this read while Go booted
    // fine). With O_NONBLOCK that read returns WouldBlock and the deadline
    // loop below stays in charge. Best-effort: if the ioctl fails we keep
    // the previous behavior.
    let _ = rustix::io::ioctl_fionbio(&tty, true);
    tty.write_all(query).ok()?;
    tty.flush().ok()?;

    let deadline = Instant::now() + timeout;
    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 256];
    // Stops on the DA1 fence, at the deadline, or on EOF/error.
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            // Explicit deadline stop: poll(2) on macOS /dev/tty can keep
            // reporting (spurious) readiness even with a zero timeout, so
            // the Ok(0) arm below is not a reliable deadline check.
            break;
        }
        let Ok(wait) = Timespec::try_from(remaining) else {
            break;
        };
        let mut fds = [PollFd::new(&tty, PollFlags::IN)];
        match rustix::event::poll(&mut fds, Some(&wait)) {
            Ok(0) => break, // deadline reached
            Ok(_) => {}
            Err(rustix::io::Errno::INTR) => continue,
            Err(_) => break,
        }
        match tty.read(&mut chunk) {
            Ok(0) => break, // EOF
            Ok(n) => {
                buf.extend_from_slice(&chunk[..n]);
                if contains_da1_reply(&buf) {
                    break;
                }
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                // Spurious poll readiness (see O_NONBLOCK note above):
                // pace the retry so a misbehaving poll cannot spin hot.
                thread::sleep(remaining.min(Duration::from_millis(10)));
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
            Err(_) => break,
        }
    }
    Some(buf)
}

/// Non-Unix: there is no /dev/tty to query; every capability stays empty.
#[cfg(not(unix))]
fn terminal_round_trip(_query: &[u8], _timeout: Duration) -> Option<Vec<u8>> {
    None
}

/// Whether `buf` contains a DA1 reply (`ESC [ ? <params> c`).
fn contains_da1_reply(buf: &[u8]) -> bool {
    let mut i = 0;
    while i + 1 < buf.len() {
        if buf[i] == 0x1b && buf[i + 1] == b'[' {
            let mut j = i + 2;
            while j < buf.len() && (buf[j].is_ascii_digit() || buf[j] == b';' || buf[j] == b'?') {
                j += 1;
            }
            if j > i + 2 && j < buf.len() && buf[j] == b'c' {
                return true;
            }
        }
        i += 1;
    }
    false
}

/// Extracts the OSC 11 reply's payload (`ESC ] 11 ; <color> BEL|ST`).
fn osc11_payload(s: &str) -> Option<&str> {
    let start = s.find("\x1b]11;")? + 5;
    let rest = &s[start..];
    let end = rest.find(['\x07', '\x1b']).unwrap_or(rest.len());
    Some(rest[..end].trim())
}

/// Extracts the OSC 11 reply and classifies the color.
fn parse_osc11_is_dark(buf: &[u8]) -> Option<bool> {
    let s = String::from_utf8_lossy(buf);
    let (r, g, b) = parse_x_color(osc11_payload(&s)?)?;
    Some(is_dark_color(r, g, b))
}

/// The same OSC 11 reply as the 8-bit RGB the runs-list zebra stripe blends
/// from (carried on `Event::BackgroundColor::rgb`).
///
/// PARITY: Go reads this through termenv's SEPARATE OSC 11 query
/// (styles.go:55-84 `initTerminalBg`); termenv's `xTermColor` accepts ONLY
/// the `rgb:RRRR/GGGG/BBBB` XParseColor form (exactly 4 hex digits per
/// component) and keeps the high byte of each. Any other reply leaves Go's
/// `termBgDetected` false → the #d0d0d0/#1c1c1c zebra fallback
/// (`get_odd_run_style_color(None)`); `None` here does the same.
fn parse_osc11_rgb(buf: &[u8]) -> Option<Rgb> {
    let s = String::from_utf8_lossy(buf);
    let spec = osc11_payload(&s)?;
    let parts: Vec<&str> = spec.strip_prefix("rgb:")?.split('/').collect();
    let [r, g, b] = parts.as_slice() else {
        return None;
    };
    let byte = |p: &str| -> Option<u8> {
        (p.len() == 4 && p.bytes().all(|c| c.is_ascii_hexdigit()))
            .then(|| u8::from_str_radix(&p[..2], 16).ok())
            .flatten()
    };
    Some(Rgb(byte(r)?, byte(g)?, byte(b)?))
}

/// Extracts the CSI 16 t reply — `ESC [ 6 ; height ; width t` (XTWINOPS;
/// ultraviolet decodes it as `uv.CellSizeEvent{Width, Height}`,
/// decoder.go:646-655) — returning (width, height) in pixels.
fn parse_cell_size_reply(buf: &[u8]) -> Option<(isize, isize)> {
    let s = String::from_utf8_lossy(buf);
    let mut rest: &str = &s;
    while let Some(start) = rest.find("\x1b[6;") {
        let tail = &rest[start + 4..];
        let end = tail
            .find(|c: char| !c.is_ascii_digit() && c != ';')
            .unwrap_or(tail.len());
        if tail[end..].starts_with('t') {
            let mut parts = tail[..end].split(';');
            if let (Some(height), Some(width), None) = (parts.next(), parts.next(), parts.next())
                && let (Ok(height), Ok(width)) = (height.parse::<isize>(), width.parse::<isize>())
            {
                return Some((width, height));
            }
        }
        rest = &rest[start + 4..];
    }
    None
}

/// Whether `buf` contains a Kitty graphics APC response
/// (`ESC _ G <opts> [; payload] ESC \`) whose `i=` option matches `id`.
///
/// PARITY: `recordKittyResponse` (kitty_capability.go:190-204) — any
/// response carrying the probe's image ID proves the terminal speaks the
/// protocol, even an error response; only a Kitty-aware terminal would have
/// produced it. The options are the comma-separated `k=v` list ultraviolet
/// feeds `kitty.Options.UnmarshalText` (decoder.go:1071-1077); only `i=`
/// matters here.
fn contains_kitty_probe_response(buf: &[u8], id: i64) -> bool {
    let s = String::from_utf8_lossy(buf);
    let mut rest: &str = &s;
    while let Some(start) = rest.find("\x1b_G") {
        let body = &rest[start + 3..];
        let end = body.find("\x1b\\").unwrap_or(body.len());
        let opts = body[..end].split(';').next().unwrap_or("");
        for opt in opts.split(',') {
            if let Some(v) = opt.strip_prefix("i=")
                && v.parse::<i64>() == Ok(id)
            {
                return true;
            }
        }
        rest = &rest[start + 3..];
    }
    false
}

/// XParseColor forms terminals actually reply with: `rgb:RRRR/GGGG/BBBB`
/// (1-4 hex digits per component, scaled) and `#RRGGBB`.
fn parse_x_color(spec: &str) -> Option<(f64, f64, f64)> {
    if let Some(rest) = spec.strip_prefix("rgb:") {
        let mut values = [0f64; 3];
        let mut count = 0;
        for (i, part) in rest.split('/').enumerate() {
            if i >= 3 || part.is_empty() || part.len() > 4 {
                return None;
            }
            let v = u32::from_str_radix(part, 16).ok()?;
            let max = (16u32.pow(part.len() as u32) - 1) as f64;
            values[i] = f64::from(v) / max;
            count = i + 1;
        }
        if count != 3 {
            return None;
        }
        return Some((values[0], values[1], values[2]));
    }
    if let Some(hex) = spec.strip_prefix('#')
        && hex.len() == 6
    {
        let v = u32::from_str_radix(hex, 16).ok()?;
        return Some((
            f64::from((v >> 16) & 0xff) / 255.0,
            f64::from((v >> 8) & 0xff) / 255.0,
            f64::from(v & 0xff) / 255.0,
        ));
    }
    None
}

/// PARITY: `tea.BackgroundColorMsg.IsDark` → lipgloss `isDarkColor`, which
/// tests HSL lightness `(max+min)/2 < 0.5`.
fn is_dark_color(r: f64, g: f64, b: f64) -> bool {
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    (max + min) / 2.0 < 0.5
}

// ---------------------------------------------------------------------------
// Terminal lifecycle
// ---------------------------------------------------------------------------

/// Raw mode + alt screen + mouse capture + title, mirroring the Go view
/// flags (model.go:253-255 / symon.go:174-177: `WindowTitle`, `AltScreen`,
/// `MouseModeCellMotion`) and Bubble Tea's hidden cursor. `window_title`
/// comes from [`App::window_title`] — `"wandb leet"` for the model,
/// `"wandb leet symon"` for symon.
///
/// PARITY: crossterm's `EnableMouseCapture` also enables all-motion
/// tracking (1003) where Bubble Tea's cell-motion mode is button-motion
/// only (1002); the extra hover events decode as `MouseButton::None`
/// motion, which no leet handler consumes. Harness runs feed both apps
/// identical PTY bytes, so parity is unaffected.
pub fn setup_terminal(window_title: &str) -> io::Result<Terminal<CrosstermBackend<io::Stdout>>> {
    enable_raw_mode()?;
    let setup = || -> io::Result<Terminal<CrosstermBackend<io::Stdout>>> {
        let mut stdout = io::stdout();
        execute!(
            stdout,
            EnterAlternateScreen,
            EnableMouseCapture,
            SetTitle(window_title),
            cursor::Hide,
            // PARITY: Bubble Tea v2 always negotiates kitty keyboard flag 1
            // (cursed_renderer.go enter(): `KittyKeyboard(1, 1)` — see
            // keyboardEnhancementsFlags, "always enable basic key
            // disambiguation"). Without this, kitty-capable terminals
            // (Ghostty, kitty) send ctrl+/ as legacy 0x1F, which decodes as
            // ctrl+_ in BOTH implementations, so the "ctrl+/" bindings never
            // fire (verified against the oracle in a scripted-Ghostty PTY).
            // With flag 1 the terminal sends CSI 47;5u, which crossterm
            // parses into Char('/')+CONTROL. Pushed after entering the alt
            // screen because the kitty spec keeps separate main/alt-screen
            // flag stacks; legacy terminals ignore the sequence.
            //
            // NOTE: Go additionally sets xterm modifyOtherKeys mode 2
            // (`CSI >4;2m`). We deliberately do NOT: crossterm cannot parse
            // the resulting `CSI 27;<mod>;<code>~` sequences — worse, an
            // unparseable sequence wedges its reader in a blocking read()
            // until the next byte arrives, going deaf to resize events. On
            // mok-only terminals (bare xterm) ctrl+/ therefore stays inert
            // in Rust where Go clears; the documented ctrl+l fallback works
            // everywhere.
            PushKeyboardEnhancementFlags(KEYBOARD_ENHANCEMENTS),
        )?;
        Terminal::new(CrosstermBackend::new(stdout))
    };
    // A failure after enable_raw_mode must not leave the process printing
    // its error into a raw-mode (and possibly alt-screen) terminal: undo
    // everything best-effort. restore_terminal's leave-alt-screen is
    // harmless when EnterAlternateScreen was queued but never flushed.
    setup().inspect_err(|_| restore_terminal())
}

/// The kitty keyboard flags every session negotiates, mirroring Bubble Tea
/// v2's baseline (flags=1, key disambiguation only: no event types, no
/// alternate keys — so terminals never send release events or shifted-key
/// sub-params leet doesn't consume).
pub(crate) const KEYBOARD_ENHANCEMENTS: KeyboardEnhancementFlags =
    KeyboardEnhancementFlags::DISAMBIGUATE_ESCAPE_CODES;

/// Best-effort restore, also invoked by the panic hook (§2.8): leave the
/// alt screen, disable raw mode + mouse capture, show the cursor.
///
/// The keyboard-enhancement pop precedes `LeaveAlternateScreen` so it acts
/// on the alt screen's flag stack (where the matching push happened);
/// popping an empty stack is a no-op per the kitty spec, so the
/// setup-failure path that runs this without a flushed push is harmless.
pub fn restore_terminal() {
    let mut stdout = io::stdout();
    let _ = execute!(
        stdout,
        cursor::Show,
        PopKeyboardEnhancementFlags,
        DisableMouseCapture,
        LeaveAlternateScreen,
    );
    let _ = disable_raw_mode();
}

/// The current session's sender plus the swap signal for the singleton
/// input thread (see [`spawn_input_thread`]).
struct InputHub {
    sender: Mutex<Sender<RuntimeEvent>>,
    swapped: Condvar,
}

static INPUT_HUB: OnceLock<InputHub> = OnceLock::new();

/// The input producer: ONE process-global thread parked in blocking
/// `crossterm::event::read()`, feeding `Event::Key`/`Mouse`/`Resize`
/// through the key.rs converters into the CURRENT session's channel.
///
/// Why a singleton (§2.9): crossterm's `read()` holds the process-global
/// `INTERNAL_EVENT_READER` lock across the whole blocking read
/// (crossterm-0.29.0 event.rs `read_internal`). A per-session thread can
/// therefore never be replaced across the alt+r restart loop — the stale
/// thread would keep the lock, swallow the first terminal event after the
/// restart (its send into the dropped channel fails), and leak one parked
/// thread per restart. Instead the thread survives restarts and each
/// session installs its sender here; an event read while no session is
/// live is held and re-sent once the next sender arrives (Go leaves those
/// bytes in the tty buffer for the next Program's reader — same outcome).
pub fn spawn_input_thread(events: Sender<RuntimeEvent>) {
    let hub = INPUT_HUB.get_or_init(|| InputHub {
        sender: Mutex::new(events.clone()),
        swapped: Condvar::new(),
    });
    // Install this session's sender; wake a delivery parked on the previous
    // session's dropped receiver.
    *lock_unpoisoned(&hub.sender) = events;
    hub.swapped.notify_all();

    static SPAWN: Once = Once::new();
    SPAWN.call_once(|| {
        let spawned = thread::Builder::new().name("input".into()).spawn(|| {
            input_thread_main(INPUT_HUB.get().expect("hub initialized above"));
        });
        if let Err(err) = spawned {
            tracing::error!(%err, "failed to spawn input thread");
        }
    });
}

fn input_thread_main(hub: &InputHub) {
    PANIC_SURVIVABLE.set(true);
    if let Err(payload) = panic::catch_unwind(AssertUnwindSafe(|| input_read_loop(hub))) {
        // A dead input thread is fatal, not degradable: without it a
        // raw-mode session cannot even be quit (no SIGINT). PARITY: an
        // input-reader panic kills the Go process outright; the session
        // ends with an error instead of hanging.
        let message = panic_message(payload.as_ref());
        send_to_current_session(
            hub,
            RuntimeEvent::InputFailed {
                message: format!("input thread panicked: {message}"),
            },
        );
    }
}

fn input_read_loop(hub: &InputHub) {
    loop {
        match crossterm::event::read() {
            Ok(raw) => {
                let mapped = match raw {
                    CtEvent::Key(key) => crate::key::KeyEvent::from_crossterm(key).map(Event::Key),
                    CtEvent::Mouse(mouse) => {
                        Some(Event::Mouse(crate::key::MouseEvent::from_crossterm(mouse)))
                    }
                    CtEvent::Resize(width, height) => Some(Event::Resize {
                        width: width as isize,
                        height: height as isize,
                    }),
                    // Focus/paste events: leet enables neither.
                    _ => None,
                };
                if let Some(event) = mapped {
                    send_to_current_session(hub, RuntimeEvent::App(event));
                }
            }
            Err(err) => {
                // PARITY: Bubble Tea forwards input reader errors to
                // Program.Run, which returns the error and restores the
                // terminal; RuntimeEvent::InputFailed makes run_loop do
                // the same instead of degrading into a deaf session.
                tracing::error!(%err, "input: read failed");
                send_to_current_session(
                    hub,
                    RuntimeEvent::InputFailed {
                        message: err.to_string(),
                    },
                );
                return;
            }
        }
    }
}

/// Sends into the current session's channel. Between sessions (the alt+r
/// restart gap) the send fails on the dropped receiver; the event is held
/// and retried when [`spawn_input_thread`] installs the next sender, so the
/// first post-restart event is never swallowed. When the process is exiting
/// for good the thread parks here until torn down with the process (like
/// Bubble Tea's reader parked in `read()`).
fn send_to_current_session(hub: &InputHub, event: RuntimeEvent) {
    let mut pending = event;
    let mut sender = lock_unpoisoned(&hub.sender);
    loop {
        match sender.send(pending) {
            Ok(()) => return,
            Err(mpsc::SendError(returned)) => {
                pending = returned;
                sender = hub
                    .swapped
                    .wait(sender)
                    .unwrap_or_else(PoisonError::into_inner);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// The loop
// ---------------------------------------------------------------------------

/// One UI session (`tea.Program.Run` equivalent). The caller owns the
/// restart loop (§2.9):
///
/// ```ignore
/// loop {
///     let mut model = Model::new(..);
///     runtime::run(&mut model)?;
///     if !model.should_restart() { break; }
/// }
/// ```
pub fn run(app: &mut dyn App) -> io::Result<()> {
    install_panic_hook();
    let mut terminal = setup_terminal(app.window_title())?;

    let (events_tx, events_rx) = mpsc::channel();
    let timers = spawn_scheduler(events_tx.clone());
    let mut effects = EffectRunner::new(events_tx.clone(), timers);
    if !test_mode::enabled() {
        // Detected once per process: from the first session on, the
        // singleton input thread owns the tty and crossterm's parser would
        // swallow (or garble) any later reply, so re-querying on an alt+r
        // restart session could never succeed anyway.
        static TERMINAL_CAPS: OnceLock<TerminalCapabilities> = OnceLock::new();
        effects.set_terminal_capabilities(
            *TERMINAL_CAPS.get_or_init(|| detect_terminal_capabilities(TERMINAL_QUERY_TIMEOUT)),
        );
    }
    spawn_input_thread(events_tx.clone());

    let initial_size = terminal.size().ok();
    let result = run_loop(
        app,
        &mut terminal,
        &events_rx,
        &mut effects,
        AckWriter::from_env(),
        initial_size,
    );
    restore_terminal();
    result
}

/// The event loop (§2.1): `recv()` → `update` → dispatch commands → draw.
/// Update and View run on this one thread.
pub fn run_loop<B: Backend>(
    app: &mut dyn App,
    terminal: &mut Terminal<B>,
    events: &Receiver<RuntimeEvent>,
    effects: &mut EffectRunner,
    mut ack: Option<AckWriter>,
    initial_size: Option<Size>,
) -> io::Result<()>
where
    B::Error: std::error::Error + Send + Sync + 'static,
{
    for command in app.init() {
        effects.dispatch(command);
    }
    if let Some(size) = initial_size {
        // PARITY: Bubble Tea delivers an initial tea.WindowSizeMsg before
        // any input.
        effects.emit(Event::Resize {
            width: size.width as isize,
            height: size.height as isize,
        });
    }

    let mut outcome: io::Result<()> = Ok(());
    'session: loop {
        let Ok(event) = events.recv() else {
            break 'session;
        };
        if let Err(err) = step(app, effects, &mut ack, event) {
            outcome = Err(err);
            break 'session;
        }
        // Drain whatever is immediately available before drawing: one draw
        // per burst (Bubble Tea's renderer coalesces repaints similarly;
        // complements the model-level suppressDraw batching, B3).
        while !effects.quit_requested() {
            let Ok(event) = events.try_recv() else {
                break;
            };
            if let Err(err) = step(app, effects, &mut ack, event) {
                outcome = Err(err);
                break 'session;
            }
        }
        if effects.quit_requested() {
            break 'session;
        }

        if let Err(err) = terminal.draw(|frame| {
            let area = frame.area();
            let text = app.view(area.as_size());
            frame.render_widget(text, area);
        }) {
            outcome = Err(io::Error::other(err));
            break 'session;
        }
        if let Some(ack) = ack.as_mut() {
            ack.ack_view();
        }
        // Go's prepare pump delivery point: the render recorded Kitty
        // placements; run the prepare pass now (App::after_draw doc). The
        // resulting render requests come back as KittyFrame events, waking
        // recv() like Go's mediaPanePrepareMsg wakes tea's loop.
        for command in app.after_draw() {
            effects.dispatch(command);
        }
    }

    // Go quit paths already ran their own cleanup (§1.6) and Cleanup is
    // idempotent; calling it unconditionally — on error exits too, honoring
    // the "called when the loop exits" contract — also fixes the Go
    // restart-loop leak (main.go:505-532, §2.9).
    app.cleanup();
    outcome
}

/// Handles one runtime event. `Err` ends the session fatally (input death);
/// everything else, including producer panics, degrades (§2.8).
fn step(
    app: &mut dyn App,
    effects: &mut EffectRunner,
    ack: &mut Option<AckWriter>,
    event: RuntimeEvent,
) -> io::Result<()> {
    match event {
        RuntimeEvent::App(event) => deliver(app, effects, ack, event),
        RuntimeEvent::Tick(id) => match id {
            // Timer fires become the message the Go tea.Tick callback
            // returns; the model never sees a raw tick (ack parity).
            TimerId::Anim(target) => deliver(app, effects, ack, target.event()),
            // Both owners deliver the same payload-less leet.HeartbeatMsg;
            // the model forwards it to both sub-models exactly like Go's
            // updateSubComponents, so per-interval ack counts match the
            // two-manager oracle (see command.rs HeartbeatOwner).
            TimerId::Heartbeat(_) => deliver(app, effects, ack, Event::Heartbeat),
            // The Go tea.Tick callback returns kittyProbeTickMsg
            // (kitty_capability.go:134-136).
            TimerId::KittyProbe => deliver(app, effects, ack, Event::KittyProbeTick),
            TimerId::DirPoll => effects.spawn_dir_scan(),
            TimerId::SymonSample => {
                // PHASE-6: symon sampling pass.
                tracing::debug!("SymonSample tick ignored (PHASE-6)");
            }
        },
        RuntimeEvent::ThreadPanicked {
            thread,
            message,
            source,
        } => {
            // §2.8: log (CaptureError-equivalent) and degrade; never exit.
            tracing::error!(thread, message, ?source, "background thread panicked");
            // A dead reader degrades model-visibly: deliver the ErrorMsg
            // its failed read would have produced (execute_read's error
            // leg) — the run view stops heartbeat + watcher on ErrorMsg
            // (runhandlers.go:86-88); workspace read errors arrive un-keyed
            // as ErrorMsg in Go too (readAllChunkCmd). The sources entry
            // was already removed by the reader's SourceRegistration guard.
            if source.is_some() {
                deliver(
                    app,
                    effects,
                    ack,
                    Event::Error(ErrorMsg {
                        err: EventError::other(format!("{thread} panicked: {message}")),
                    }),
                );
            }
        }
        RuntimeEvent::InputFailed { message } => {
            return Err(io::Error::other(format!("input: {message}")));
        }
    }
    Ok(())
}

fn deliver(
    app: &mut dyn App,
    effects: &mut EffectRunner,
    ack: &mut Option<AckWriter>,
    event: Event,
) {
    let ack_name = event.ack_name();
    let commands = app.update(event);
    // Go defers testAckUpdate, so it fires after Update returns.
    if let Some(ack) = ack.as_mut() {
        ack.ack_update(ack_name);
    }
    for command in commands {
        effects.dispatch(command);
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};

    use pretty_assertions::assert_eq;
    use ratatui::backend::TestBackend;

    use super::*;
    use crate::command::{AnimTarget, HeartbeatOwner};
    use crate::key::{KeyCode, KeyEvent, KeyMods};

    fn recv_app_event(rx: &Receiver<RuntimeEvent>, what: &str) -> Event {
        match rx.recv_timeout(Duration::from_secs(10)) {
            Ok(RuntimeEvent::App(event)) => event,
            other => panic!("expected App event for {what}, got {other:?}"),
        }
    }

    // -- Keyboard-enhancement negotiation -------------------------------------

    /// Regression: every session must negotiate kitty key disambiguation
    /// (flags=1), like Bubble Tea v2's renderer. Without the push, Ghostty/
    /// kitty send ctrl+/ as legacy 0x1F = ctrl+_ and the "ctrl+/" bindings
    /// (clear metrics filter) can never fire; with it they send CSI 47;5u.
    /// Pins the exact bytes so a crossterm upgrade can't silently change
    /// what we request, and that the pop is the matching stack operation.
    #[test]
    fn keyboard_enhancement_negotiation_bytes() {
        use crossterm::Command as _;

        assert_eq!(KEYBOARD_ENHANCEMENTS.bits(), 1, "must match Go's flags=1");

        let mut push = String::new();
        PushKeyboardEnhancementFlags(KEYBOARD_ENHANCEMENTS)
            .write_ansi(&mut push)
            .unwrap();
        assert_eq!(push, "\x1b[>1u");

        let mut pop = String::new();
        PopKeyboardEnhancementFlags.write_ansi(&mut pop).unwrap();
        assert_eq!(pop, "\x1b[<1u");
    }

    // -- Scheduler (§2.4) ----------------------------------------------------

    /// Arm REPLACES the pending entry with the same tag: the original
    /// (shorter) deadline must never fire.
    #[test]
    fn scheduler_arm_replaces_entry_no_stale_fire() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx);

        timers
            .send(TimerCmd::Arm(
                TimerId::Heartbeat(HeartbeatOwner::Run),
                Duration::from_millis(50),
            ))
            .unwrap();
        timers
            .send(TimerCmd::Arm(
                TimerId::Heartbeat(HeartbeatOwner::Run),
                Duration::from_millis(400),
            ))
            .unwrap();

        // Quiet well past the replaced 50ms deadline.
        assert!(
            events_rx.recv_timeout(Duration::from_millis(200)).is_err(),
            "stale (replaced) timer fired"
        );
        // The replacement fires exactly once.
        match events_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(RuntimeEvent::Tick(TimerId::Heartbeat(HeartbeatOwner::Run))) => {}
            other => panic!("expected heartbeat tick, got {other:?}"),
        }
        // One-shot: the entry was removed on fire.
        assert!(events_rx.recv_timeout(Duration::from_millis(300)).is_err());

        // Re-arming after a fire works (handler re-arm pattern).
        timers
            .send(TimerCmd::Arm(
                TimerId::Heartbeat(HeartbeatOwner::Run),
                Duration::from_millis(10),
            ))
            .unwrap();
        match events_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(RuntimeEvent::Tick(TimerId::Heartbeat(HeartbeatOwner::Run))) => {}
            other => panic!("expected re-armed tick, got {other:?}"),
        }
    }

    /// The two Go HeartbeatManagers (run.go:159, workspace.go:176) are
    /// independent wheel keys: the run view stopping its heartbeat on a
    /// finished run (runhandlers.go:931-934) must not kill the workspace's
    /// safety net.
    #[test]
    fn heartbeat_owner_keys_are_independent() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx);

        timers
            .send(TimerCmd::Arm(
                TimerId::Heartbeat(HeartbeatOwner::Run),
                Duration::from_millis(100),
            ))
            .unwrap();
        timers
            .send(TimerCmd::Arm(
                TimerId::Heartbeat(HeartbeatOwner::Workspace),
                Duration::from_millis(300),
            ))
            .unwrap();
        timers
            .send(TimerCmd::Cancel(TimerId::Heartbeat(HeartbeatOwner::Run)))
            .unwrap();

        match events_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(RuntimeEvent::Tick(TimerId::Heartbeat(HeartbeatOwner::Workspace))) => {}
            other => panic!("expected workspace heartbeat tick, got {other:?}"),
        }
        assert!(
            events_rx.recv_timeout(Duration::from_millis(200)).is_err(),
            "cancelled run heartbeat fired"
        );
    }

    #[test]
    fn scheduler_cancel_prevents_fire() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx);

        timers
            .send(TimerCmd::Arm(TimerId::DirPoll, Duration::from_millis(30)))
            .unwrap();
        timers.send(TimerCmd::Cancel(TimerId::DirPoll)).unwrap();
        assert!(
            events_rx.recv_timeout(Duration::from_millis(200)).is_err(),
            "cancelled timer fired"
        );
    }

    /// Distinct ids are independent entries and fire in deadline order.
    #[test]
    fn scheduler_ids_are_independent() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx);

        timers
            .send(TimerCmd::Arm(
                TimerId::Anim(AnimTarget::MediaPane),
                Duration::from_millis(60),
            ))
            .unwrap();
        timers
            .send(TimerCmd::Arm(
                TimerId::Anim(AnimTarget::LeftSidebar),
                Duration::from_millis(10),
            ))
            .unwrap();

        let first = events_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        let second = events_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert!(
            matches!(
                first,
                RuntimeEvent::Tick(TimerId::Anim(AnimTarget::LeftSidebar))
            ),
            "got {first:?}"
        );
        assert!(
            matches!(
                second,
                RuntimeEvent::Tick(TimerId::Anim(AnimTarget::MediaPane))
            ),
            "got {second:?}"
        );
    }

    // -- Ack protocol (testmode.go) ------------------------------------------

    #[derive(Clone, Default)]
    struct SharedBuf(Arc<Mutex<Vec<u8>>>);

    impl SharedBuf {
        fn contents(&self) -> String {
            String::from_utf8(lock_unpoisoned(&self.0).clone()).unwrap()
        }
    }

    impl Write for SharedBuf {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            lock_unpoisoned(&self.0).extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    /// The lines must be byte-identical to testmode.go's
    /// `fmt.Fprintf(s.f, "u %d %T\n", seq, msg)` / `"v %d\n"` — e.g.
    /// "u 12 tea.KeyPressMsg" / "v 12".
    #[test]
    fn ack_lines_match_testmode_go_format() {
        let buf = SharedBuf::default();
        let mut ack = AckWriter::new(Box::new(buf.clone()));

        for _ in 0..11 {
            ack.ack_update(Event::Heartbeat.ack_name());
        }
        let key = Event::Key(KeyEvent {
            code: KeyCode::Char('q'),
            text: Some("q".into()),
            mods: KeyMods::NONE,
        });
        ack.ack_update(key.ack_name());
        ack.ack_view();

        let contents = buf.contents();
        let lines: Vec<&str> = contents.lines().collect();
        assert_eq!(lines.len(), 13);
        assert_eq!(lines[0], "u 1 leet.HeartbeatMsg");
        assert_eq!(lines[11], "u 12 tea.KeyPressMsg");
        assert_eq!(lines[12], "v 12");
    }

    /// `from_env` hands out clones of ONE process-global state (Go
    /// testAckState is a `sync.OnceValue` with an `atomic.Int64` seq): the
    /// seq must continue across alt+r restart sessions, not reset to 0 —
    /// otherwise stale high-seq `v` lines in the harness history satisfy
    /// `await_view` before the awaited frame renders.
    #[test]
    fn ack_writer_handles_share_seq_across_sessions() {
        let buf = SharedBuf::default();
        let mut session1 = AckWriter::new(Box::new(buf.clone()));
        session1.ack_update(Event::Heartbeat.ack_name());
        session1.ack_view();

        // The restart loop's next run() gets a handle to the same state.
        let mut session2 = session1.clone();
        session2.ack_update(Event::Heartbeat.ack_name());
        session2.ack_view();

        assert_eq!(
            buf.contents(),
            "u 1 leet.HeartbeatMsg\nv 1\nu 2 leet.HeartbeatMsg\nv 2\n"
        );
    }

    // -- Command dispatch: reader round-trip against the fixture --------------

    fn fixture_wandb_file() -> String {
        concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../fixtures/wandb/single-tiny/wandb/run-20260102_030405-tiny0001/run-tiny0001.wandb"
        )
        .to_string()
    }

    /// End-to-end thread round-trip: InitReader spawns the reader thread,
    /// ReadChunk flows through its request queue, records come back as
    /// events, CloseReader ends it (§2.3/§2.9).
    #[test]
    fn read_chunk_round_trip_against_fixture() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx, timers);

        effects.dispatch(Command::InitReader {
            run_path: fixture_wandb_file(),
        });
        let Event::Init(init) = recv_app_event(&events_rx, "InitMsg") else {
            panic!("expected Init");
        };
        let source = init.source.id;
        assert_ne!(source, SourceId::default());
        assert_eq!(effects.source_count(), 1);

        effects.dispatch(Command::ReadChunk {
            source,
            chunk_size: BOOT_LOAD_CHUNK_SIZE,
            max_time_per_chunk: BOOT_LOAD_MAX_TIME,
        });
        let Event::ChunkedBatch(batch) = recv_app_event(&events_rx, "ChunkedBatchMsg") else {
            panic!("expected ChunkedBatch");
        };
        assert!(batch.progress > 0);
        let run = batch.msgs.iter().find_map(|m| match m {
            Event::Run(run) => Some(run),
            _ => None,
        });
        assert_eq!(run.expect("fixture contains a Run record").id, "tiny0001");

        // The fixture ends with an exit record: the batch reports the run
        // complete and no further data.
        assert!(
            batch
                .msgs
                .iter()
                .any(|m| matches!(m, Event::FileComplete(_)))
        );
        assert!(!batch.has_more);

        effects.dispatch(Command::CloseReader { source });
        // The request sender is gone; further reads are dropped silently
        // (Go: read cmd with nil source returns nil).
        effects.dispatch(Command::ReadLiveBatch { source });
        assert!(events_rx.recv_timeout(Duration::from_millis(200)).is_err());
        assert_eq!(effects.source_count(), 0);
    }

    /// The workspace variants carry the run key end to end.
    #[test]
    fn workspace_read_round_trip_against_fixture() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx, timers);

        effects.dispatch(Command::InitWorkspaceReader {
            run_key: "run-20260102_030405-tiny0001".into(),
            run_path: fixture_wandb_file(),
        });
        let Event::WorkspaceRunInit(init) = recv_app_event(&events_rx, "WorkspaceRunInitMsg")
        else {
            panic!("expected WorkspaceRunInit");
        };
        assert_eq!(init.run_key, "run-20260102_030405-tiny0001");
        assert!(init.run_path.ends_with("run-tiny0001.wandb"));

        effects.dispatch(Command::ReadAllChunk {
            source: init.reader.id,
            run_key: init.run_key.clone(),
        });
        let Event::WorkspaceChunkedBatch(batch) =
            recv_app_event(&events_rx, "WorkspaceChunkedBatchMsg")
        else {
            panic!("expected WorkspaceChunkedBatch");
        };
        assert_eq!(batch.run_key, init.run_key);
        assert!(batch.batch.progress > 0);
    }

    #[test]
    fn init_reader_error_paths() {
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx, timers);

        // Single-run mode reproduces Go's exact error prefix
        // (leveldbhistorysource.go:60-64).
        effects.dispatch(Command::InitReader {
            run_path: "/nonexistent/run.wandb".into(),
        });
        let Event::Error(err) = recv_app_event(&events_rx, "ErrorMsg") else {
            panic!("expected Error");
        };
        assert!(
            err.err
                .message
                .starts_with("leveldbhistory: failed to create live store:"),
            "got {:?}",
            err.err.message
        );

        // Workspace mode keys the error to the run and classifies NotExist
        // (workspacehandlers.go:597-611 checks os.IsNotExist).
        effects.dispatch(Command::InitWorkspaceReader {
            run_key: "run-x".into(),
            run_path: "/nonexistent/run.wandb".into(),
        });
        let Event::WorkspaceInitErr(err) = recv_app_event(&events_rx, "WorkspaceInitErrMsg") else {
            panic!("expected WorkspaceInitErr");
        };
        assert_eq!(err.run_key, "run-x");
        assert_eq!(
            err.err.as_ref().map(|e| e.kind),
            Some(EventErrorKind::NotExist)
        );
    }

    // -- Preload effect (workspacedirwatcher.go) ------------------------------

    #[test]
    fn preload_run_overview_finds_run_record() {
        let msg = preload_run_overview("run-20260102_030405-tiny0001", &fixture_wandb_file());
        assert_eq!(msg.err, None);
        assert_eq!(msg.run.expect("run record").id, "tiny0001");
    }

    #[test]
    fn preload_run_overview_error_classification() {
        // Empty key/path → the errRunRecordNotFound sentinel.
        let msg = preload_run_overview("", "whatever");
        assert_eq!(
            msg.err.map(|e| e.kind),
            Some(EventErrorKind::RunRecordNotFound)
        );

        // Missing file → os.IsNotExist equivalent
        // (workspacedirwatcher.go:293 skips logging for it).
        let msg = preload_run_overview("run-x", "/nonexistent/run.wandb");
        assert_eq!(msg.run, None);
        assert_eq!(msg.err.map(|e| e.kind), Some(EventErrorKind::NotExist));
    }

    // -- Dir scan (workspacedirwatcher.go scanWandbRunDirs) -------------------

    #[test]
    fn scan_wandb_run_dirs_sorts_most_recent_first() {
        let dir = tempfile::tempdir().unwrap();
        for name in [
            "run-20260101_000000-aaa",
            "run-20260102_000000-bbb",
            "offline-run-20260103_000000-ccc",
            "run-badstamp",
            "notarun-20260104_000000-ddd",
        ] {
            std::fs::create_dir(dir.path().join(name)).unwrap();
        }

        let (keys, err) = scan_wandb_run_dirs(dir.path().to_str().unwrap());
        assert_eq!(err, None);
        assert_eq!(
            keys,
            vec![
                // Descending timestamp; unparsable stamp = zero time, last.
                "offline-run-20260103_000000-ccc".to_string(),
                "run-20260102_000000-bbb".to_string(),
                "run-20260101_000000-aaa".to_string(),
                "run-badstamp".to_string(),
            ]
        );

        // Empty dir string: Go returns (nil, nil).
        assert_eq!(scan_wandb_run_dirs(""), (Vec::new(), None));

        // Missing dir: error classified NotExist.
        let (keys, err) = scan_wandb_run_dirs("/nonexistent/wandb-dir");
        assert!(keys.is_empty());
        assert_eq!(err.map(|e| e.kind), Some(EventErrorKind::NotExist));
    }

    /// Mirrors Go time.Parse("20060102_150405", ..) accept/reject behavior.
    #[test]
    fn parse_run_dir_timestamp_cases() {
        let cases: &[(&str, Option<&str>)] = &[
            ("run-20260102_030405-tiny0001", Some("20260102_030405")),
            ("offline-run-20241231_235959-x", Some("20241231_235959")),
            ("run-20240229_000000-leap", Some("20240229_000000")),
            ("run-20230229_000000-noleap", None), // Feb 29 in a non-leap year
            ("run-20261301_000000-x", None),      // month 13
            ("run-20260132_000000-x", None),      // day 32
            ("run-20260101_240000-x", None),      // hour 24
            ("run-20260101_006000-x", None),      // minute 60
            ("run-20260101_000060-x", None),      // second 60
            ("run-20260101-short", None),         // < 15 chars
            ("run-2026010a_000000-x", None),      // non-digit
            ("run-20260101x000000-x", None),      // missing underscore
            ("checkpoint-20260101_000000", None), // wrong prefix
        ];
        for (name, want) in cases {
            assert_eq!(
                parse_run_dir_timestamp(name).as_deref(),
                *want,
                "case {name:?}"
            );
        }
    }

    // -- Terminal capability queries -------------------------------------------

    /// The query bytes must match Go exactly: `ansi.WindowOp(16)`
    /// (picture.go:490-492) and `buildKittyQueryAPC`
    /// (kitty_capability.go:181-183).
    #[test]
    fn capability_query_bytes_match_go() {
        assert_eq!(CELL_SIZE_QUERY, b"\x1b[16t");
        assert_eq!(
            build_kitty_query_apc(KITTY_PROBE_ID),
            "\x1b_Ga=q,t=d,f=24,s=1,v=1,i=42069101;AAAA\x1b\\"
        );
        assert_eq!(KITTY_PROBE_TIMEOUT, Duration::from_millis(250));
    }

    /// Table from kitty_capability.go:147-175 `kittyEnvSignal` — note the
    /// EXACT, case-sensitive TERM/TERM_PROGRAM matches (unlike mediapane.go's
    /// lowercased heuristic).
    #[test]
    fn kitty_env_signal_recognized_signals() {
        let signal = |key: &'static str, value: &'static str| {
            kitty_env_signal_from(|k| {
                if k == key {
                    value.to_string()
                } else {
                    String::new()
                }
            })
        };
        assert!(signal("KITTY_WINDOW_ID", "1"));
        assert!(signal("KITTY_INSTALLATION_DIR", "/apps/kitty"));
        assert!(signal("GHOSTTY_RESOURCES_DIR", "/apps/ghostty"));
        assert!(signal("WEZTERM_EXECUTABLE", "/bin/wezterm"));
        assert!(signal("WEZTERM_PANE", "0"));
        assert!(signal("TERM", "xterm-kitty"));
        assert!(signal("TERM", "xterm-ghostty"));
        assert!(signal("TERM_PROGRAM", "ghostty"));
        assert!(signal("TERM_PROGRAM", "WezTerm"));
        assert!(signal("TERM_PROGRAM", "kitty"));
        assert!(signal("TERM_PROGRAM", "iTerm.app"));

        // Not recognized by the probe gate.
        assert!(!signal("TERM", "xterm-256color"));
        assert!(!signal("TERM_PROGRAM", "Ghostty")); // case-sensitive
        assert!(!signal("TERM_PROGRAM", "wezterm")); // case-sensitive
        assert!(!signal("GHOSTTY_BIN_DIR", "/apps/ghostty")); // mediapane-only signal
        assert!(!kitty_env_signal_from(|_| String::new()));
    }

    /// `CSI 6 ; height ; width t` → (width, height), matching ultraviolet's
    /// decoder (decoder.go:646-655).
    #[test]
    fn cell_size_reply_parsing() {
        assert_eq!(parse_cell_size_reply(b"\x1b[6;20;10t"), Some((10, 20)));
        // Embedded among the other startup replies (OSC 11 + DA1 fence).
        assert_eq!(
            parse_cell_size_reply(b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07\x1b[6;32;15t\x1b[?65;1;9c"),
            Some((15, 32))
        );
        // Wrong window op (4 = pixel size, 8 = cells), wrong param counts,
        // non-numeric params, missing final byte: no reply.
        assert_eq!(parse_cell_size_reply(b"\x1b[4;200;100t"), None);
        assert_eq!(parse_cell_size_reply(b"\x1b[6;20t"), None);
        assert_eq!(parse_cell_size_reply(b"\x1b[6;20;10;5t"), None);
        assert_eq!(parse_cell_size_reply(b"\x1b[6;a;10t"), None);
        assert_eq!(parse_cell_size_reply(b"\x1b[6;20;10"), None);
        assert_eq!(parse_cell_size_reply(b""), None);
        // A lookalike prefixed by other digits must not match.
        assert_eq!(parse_cell_size_reply(b"\x1b[16;20;10t"), None);
        // First malformed candidate does not mask a later valid reply.
        assert_eq!(
            parse_cell_size_reply(b"\x1b[6;20\x1b[6;18;9t"),
            Some((9, 18))
        );
    }

    /// Any APC response carrying the probe's image ID counts — even an
    /// error response (kitty_capability.go:190-204).
    #[test]
    fn kitty_probe_response_detection() {
        // The canonical OK response.
        assert!(contains_kitty_probe_response(
            b"\x1b_Gi=42069101;OK\x1b\\",
            KITTY_PROBE_ID
        ));
        // Error responses still prove protocol support.
        assert!(contains_kitty_probe_response(
            b"\x1b_Gi=42069101;EINVAL:bad image\x1b\\",
            KITTY_PROBE_ID
        ));
        // Extra options around i=.
        assert!(contains_kitty_probe_response(
            b"\x1b_Gq=2,i=42069101,p=1;OK\x1b\\",
            KITTY_PROBE_ID
        ));
        // Embedded among the other startup replies.
        assert!(contains_kitty_probe_response(
            b"\x1b]11;rgb:0/0/0\x07\x1b[6;20;10t\x1b_Gi=42069101;OK\x1b\\\x1b[?6c",
            KITTY_PROBE_ID
        ));
        // A different image ID is not our probe.
        assert!(!contains_kitty_probe_response(
            b"\x1b_Gi=7;OK\x1b\\",
            KITTY_PROBE_ID
        ));
        // An ID that merely contains ours as a prefix must not match.
        assert!(!contains_kitty_probe_response(
            b"\x1b_Gi=420691011;OK\x1b\\",
            KITTY_PROBE_ID
        ));
        assert!(!contains_kitty_probe_response(b"\x1b[?6c", KITTY_PROBE_ID));
        assert!(!contains_kitty_probe_response(b"", KITTY_PROBE_ID));
    }

    /// The decision half of picture.QueryKittySupport
    /// (kitty_capability.go:116-140).
    #[test]
    fn plan_kitty_query_cases() {
        // Already resolved (ForceKittyCapability before Init): skip.
        assert_eq!(
            plan_kitty_query(KittyCapability::Supported, true, true),
            KittyQueryPlan::Noop
        );
        assert_eq!(
            plan_kitty_query(KittyCapability::Unsupported, true, true),
            KittyQueryPlan::Noop
        );
        // Env preflight negative: resolve Unsupported, nothing on the wire.
        assert_eq!(
            plan_kitty_query(KittyCapability::Unknown, false, false),
            KittyQueryPlan::ResolveUnsupported
        );
        // Probe sent: deliver the captured outcome + the timeout tick.
        assert_eq!(
            plan_kitty_query(KittyCapability::Unknown, true, true),
            KittyQueryPlan::Await { responded: true }
        );
        assert_eq!(
            plan_kitty_query(KittyCapability::Unknown, true, false),
            KittyQueryPlan::Await { responded: false }
        );
    }

    /// RequestCellSize replays the captured reply as uv.CellSizeEvent (no
    /// reply → no message, like a non-answering terminal in Go).
    #[test]
    fn request_cell_size_replays_captured_reply() {
        let (events_tx, events_rx) = mpsc::channel();
        let (timers_tx, _timers_rx) = mpsc::channel();
        let mut effects = EffectRunner::new(events_tx, timers_tx);

        effects.dispatch(Command::RequestCellSize);
        assert!(
            events_rx.recv_timeout(Duration::from_millis(100)).is_err(),
            "no captured reply must produce no event"
        );

        effects.set_terminal_capabilities(TerminalCapabilities {
            cell_size: Some((10, 20)),
            ..TerminalCapabilities::default()
        });
        effects.dispatch(Command::RequestCellSize);
        let event = recv_app_event(&events_rx, "CellSizeEvent");
        assert_eq!(
            event,
            Event::CellSize {
                width: 10,
                height: 20
            }
        );
        assert_eq!(event.ack_name(), "uv.CellSizeEvent");
    }

    /// The Await leg mirrors Go's tea.Batch(tea.Raw(probe), tea.Tick(250ms)):
    /// the captured response (if any) is delivered as uv.KittyGraphicsEvent
    /// and the probe-timeout tick is ALWAYS armed — a late tick no-ops in
    /// recordKittyTimeout once the capability is Supported.
    /// (The plan's global side-effect legs are covered by
    /// plan_kitty_query_cases + media_pane's record_* tests; this test must
    /// not touch the process-wide capability static.)
    #[test]
    fn kitty_query_await_emits_response_and_arms_timeout() {
        let (events_tx, events_rx) = mpsc::channel();
        let (timers_tx, timers_rx) = mpsc::channel();
        let effects = EffectRunner::new(events_tx, timers_tx);

        effects.run_kitty_query_plan(KittyQueryPlan::Await { responded: true });
        let event = recv_app_event(&events_rx, "KittyGraphicsEvent");
        assert_eq!(
            event,
            Event::KittyGraphics(crate::event::KittyGraphicsMsg { id: KITTY_PROBE_ID })
        );
        assert_eq!(event.ack_name(), "uv.KittyGraphicsEvent");
        assert_eq!(
            timers_rx.recv_timeout(Duration::from_secs(5)).unwrap(),
            TimerCmd::Arm(TimerId::KittyProbe, KITTY_PROBE_TIMEOUT)
        );

        // No response: only the timeout tick.
        effects.run_kitty_query_plan(KittyQueryPlan::Await { responded: false });
        assert_eq!(
            timers_rx.recv_timeout(Duration::from_secs(5)).unwrap(),
            TimerCmd::Arm(TimerId::KittyProbe, KITTY_PROBE_TIMEOUT)
        );
        assert!(events_rx.recv_timeout(Duration::from_millis(100)).is_err());

        // Noop does nothing at all.
        effects.run_kitty_query_plan(KittyQueryPlan::Noop);
        assert!(events_rx.recv_timeout(Duration::from_millis(100)).is_err());
        assert!(timers_rx.try_recv().is_err());
    }

    /// The KittyProbe timer fire is translated to the message the Go
    /// tea.Tick callback returns (kitty_capability.go:134-136).
    #[test]
    fn kitty_probe_tick_delivers_probe_tick_msg() {
        let mut app = StubApp {
            seen: Vec::new(),
            cleaned_up: Arc::new(AtomicBool::new(false)),
        };
        let (events_tx, _events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx, timers);
        let mut ack = None;

        step(
            &mut app,
            &mut effects,
            &mut ack,
            RuntimeEvent::Tick(TimerId::KittyProbe),
        )
        .unwrap();
        assert_eq!(app.seen, vec!["picture.kittyProbeTickMsg"]);
    }

    // -- Background color parsing ---------------------------------------------

    #[test]
    fn osc11_reply_parsing_and_darkness() {
        // xterm-style 16-bit reply, dark background, BEL-terminated,
        // followed by the DA1 fence reply.
        let reply = b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07\x1b[?65;1;9c";
        assert!(contains_da1_reply(reply));
        assert_eq!(parse_osc11_is_dark(reply), Some(true));
        assert_eq!(parse_osc11_rgb(reply), Some(Rgb(0x1e, 0x1e, 0x1e)));

        // Light background, ST-terminated.
        let reply = b"\x1b]11;rgb:ffff/ffff/ffff\x1b\\";
        assert_eq!(parse_osc11_is_dark(reply), Some(false));
        assert_eq!(parse_osc11_rgb(reply), Some(Rgb(0xff, 0xff, 0xff)));

        // Non-duplicated 16-bit components: the high byte wins, like
        // termenv's `"#" + s[0:2] + s[4:6] + s[8:10]`.
        let reply = b"\x1b]11;rgb:1234/5678/9abc\x07";
        assert_eq!(parse_osc11_rgb(reply), Some(Rgb(0x12, 0x56, 0x9a)));

        // 2-digit components scale by their own width for the dark flag...
        let reply = b"\x1b]11;rgb:20/20/20\x07";
        assert_eq!(parse_osc11_is_dark(reply), Some(true));
        // ...but termenv rejects them (its length check requires 4 hex
        // digits per component), so Go's zebra keeps the fallback.
        assert_eq!(parse_osc11_rgb(reply), None);

        // #RRGGBB form: same split — Bubble Tea decodes it, termenv doesn't.
        let reply = b"\x1b]11;#f0f0f0\x07";
        assert_eq!(parse_osc11_is_dark(reply), Some(false));
        assert_eq!(parse_osc11_rgb(reply), None);

        // DA1-only reply (terminal ignored OSC 11): no answer.
        let reply = b"\x1b[?6c";
        assert!(contains_da1_reply(reply));
        assert_eq!(parse_osc11_is_dark(reply), None);
        assert_eq!(parse_osc11_rgb(reply), None);

        // Garbage: no answer, no fence.
        assert!(!contains_da1_reply(b"hello"));
        assert_eq!(parse_osc11_is_dark(b"hello"), None);
        assert_eq!(parse_osc11_rgb(b"hello"), None);
    }

    // -- run_loop end-to-end ---------------------------------------------------

    /// Records delivered events; quits on 'q'; proves update-returned
    /// commands dispatch (Emit round-trips through the queue).
    struct StubApp {
        seen: Vec<String>,
        cleaned_up: Arc<AtomicBool>,
    }

    impl App for StubApp {
        fn init(&mut self) -> Vec<Command> {
            Vec::new()
        }

        fn update(&mut self, event: Event) -> Vec<Command> {
            self.seen.push(event.ack_name().to_string());
            match event {
                Event::Key(key) if key.code == KeyCode::Char('q') => vec![Command::Quit],
                // First heartbeat: emit a synthetic resize (the
                // model.go:404-407 shape).
                Event::Heartbeat => vec![Command::Emit(Box::new(Event::Resize {
                    width: 100,
                    height: 40,
                }))],
                _ => Vec::new(),
            }
        }

        fn view(&mut self, _size: Size) -> Text<'static> {
            Text::from("stub")
        }

        fn window_title(&self) -> &str {
            "wandb leet"
        }

        fn should_restart(&self) -> bool {
            false
        }

        fn cleanup(&mut self) {
            self.cleaned_up.store(true, Ordering::SeqCst);
        }
    }

    #[test]
    fn run_loop_delivers_acks_and_quits() {
        let cleaned_up = Arc::new(AtomicBool::new(false));
        let mut app = StubApp {
            seen: Vec::new(),
            cleaned_up: Arc::clone(&cleaned_up),
        };

        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx.clone(), timers);
        let ack_buf = SharedBuf::default();
        let ack = AckWriter::new(Box::new(ack_buf.clone()));

        // Feed a heartbeat, then send 'q' only after the first frame has
        // been acked (so at least one draw happens deterministically).
        events_tx.send(RuntimeEvent::App(Event::Heartbeat)).unwrap();
        let watcher_buf = ack_buf.clone();
        let quit_tx = events_tx.clone();
        thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(10);
            while !watcher_buf.contents().contains("v ") {
                if Instant::now() > deadline {
                    break;
                }
                thread::sleep(Duration::from_millis(2));
            }
            let _ = quit_tx.send(RuntimeEvent::App(Event::Key(KeyEvent {
                code: KeyCode::Char('q'),
                text: Some("q".into()),
                mods: KeyMods::NONE,
            })));
        });

        let mut terminal = Terminal::new(TestBackend::new(20, 6)).unwrap();
        run_loop(
            &mut app,
            &mut terminal,
            &events_rx,
            &mut effects,
            Some(ack),
            Some(Size::new(80, 24)),
        )
        .unwrap();

        // The pre-queued heartbeat, the initial Bubble-Tea-style
        // WindowSizeMsg (emitted inside run_loop, so after the pre-queued
        // event), the Emit'ed synthetic resize, then the quit key.
        assert_eq!(
            app.seen,
            vec![
                "leet.HeartbeatMsg",
                "tea.WindowSizeMsg",
                "tea.WindowSizeMsg",
                "tea.KeyPressMsg",
            ]
        );
        assert!(cleaned_up.load(Ordering::SeqCst), "cleanup not called");

        let contents = ack_buf.contents();
        let lines: Vec<&str> = contents.lines().collect();
        // Update acks carry 1-based seq + the Go %T name; every draw acks
        // the latest update seq. The quit key is acked but not drawn.
        assert_eq!(lines[0], "u 1 leet.HeartbeatMsg");
        assert!(lines.contains(&"u 2 tea.WindowSizeMsg"));
        assert!(lines.contains(&"u 3 tea.WindowSizeMsg"));
        assert_eq!(lines.last().unwrap(), &"u 4 tea.KeyPressMsg");
        assert!(lines.iter().any(|l| l.starts_with("v ")));
    }

    /// ThreadPanicked degrades (logs) instead of crashing the loop, and a
    /// panicking effect thread reports itself (§2.8).
    #[test]
    fn thread_panic_reports_and_loop_degrades() {
        let (events_tx, events_rx) = mpsc::channel();
        spawn_guarded("boom", events_tx, |_| panic!("kaput"));
        match events_rx.recv_timeout(Duration::from_secs(10)) {
            Ok(RuntimeEvent::ThreadPanicked {
                thread,
                message,
                source,
            }) => {
                assert_eq!(thread, "boom");
                assert_eq!(message, "kaput");
                assert_eq!(source, None);
            }
            other => panic!("expected ThreadPanicked, got {other:?}"),
        }
    }

    /// A panic unwinding out of the reader body must still deregister the
    /// sources entry (§2.8): a stale entry would over-report source_count
    /// and break the Go nil-source no-op on later reads.
    #[test]
    fn reader_panic_deregisters_source_entry() {
        let sources: SourceMap = Arc::new(Mutex::new(HashMap::new()));
        let (tx, _rx) = mpsc::channel();
        lock_unpoisoned(&sources).insert(SourceId(7), tx);

        let unwound = panic::catch_unwind(AssertUnwindSafe(|| {
            let _registration = SourceRegistration {
                sources: Arc::clone(&sources),
                id: SourceId(7),
            };
            panic!("reader boom");
        }));
        assert!(unwound.is_err());
        assert!(
            lock_unpoisoned(&sources).is_empty(),
            "panicked reader left a stale sources entry"
        );
    }

    /// A reader-thread panic is delivered to the model as the ErrorMsg its
    /// failed read would have produced (§2.8 degrade: the run view stops
    /// heartbeat + watcher on ErrorMsg); sourceless producer panics only
    /// log.
    #[test]
    fn reader_thread_panic_degrades_to_model_visible_error() {
        let mut app = StubApp {
            seen: Vec::new(),
            cleaned_up: Arc::new(AtomicBool::new(false)),
        };
        let (events_tx, _events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx, timers);
        let mut ack = None;

        step(
            &mut app,
            &mut effects,
            &mut ack,
            RuntimeEvent::ThreadPanicked {
                thread: "reader-1".into(),
                message: "kaput".into(),
                source: Some(SourceId(1)),
            },
        )
        .unwrap();
        assert_eq!(app.seen, vec!["leet.ErrorMsg"]);

        step(
            &mut app,
            &mut effects,
            &mut ack,
            RuntimeEvent::ThreadPanicked {
                thread: "watcher-pump".into(),
                message: "kaput".into(),
                source: None,
            },
        )
        .unwrap();
        assert_eq!(app.seen.len(), 1, "sourceless panic must not reach the app");
    }

    /// InputFailed is fatal (Bubble Tea returns input reader errors from
    /// Program.Run): the session ends with the error AND App::cleanup still
    /// runs — the loop-exit contract holds on error paths.
    #[test]
    fn input_failure_ends_session_with_error_and_cleanup() {
        let cleaned_up = Arc::new(AtomicBool::new(false));
        let mut app = StubApp {
            seen: Vec::new(),
            cleaned_up: Arc::clone(&cleaned_up),
        };
        let (events_tx, events_rx) = mpsc::channel();
        let timers = spawn_scheduler(events_tx.clone());
        let mut effects = EffectRunner::new(events_tx.clone(), timers);
        events_tx
            .send(RuntimeEvent::InputFailed {
                message: "tty gone".into(),
            })
            .unwrap();

        let mut terminal = Terminal::new(TestBackend::new(20, 6)).unwrap();
        let err = run_loop(
            &mut app,
            &mut terminal,
            &events_rx,
            &mut effects,
            None,
            None,
        )
        .expect_err("input failure must end the session with an error");
        assert!(err.to_string().contains("tty gone"), "got {err}");
        assert!(
            cleaned_up.load(Ordering::SeqCst),
            "cleanup skipped on error exit"
        );
    }
}
