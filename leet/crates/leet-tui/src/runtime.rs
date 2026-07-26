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
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, Once, OnceLock, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use crossterm::event::{DisableMouseCapture, EnableMouseCapture, Event as CtEvent};
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, SetTitle, disable_raw_mode, enable_raw_mode,
};
use crossterm::{cursor, execute};
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
    ErrorMsg, Event, EventError, EventErrorKind, HistorySourceHandle, InitMsg,
    WorkspaceFileChangedMsg, WorkspaceInitErrMsg, WorkspaceRunDirsMsg, WorkspaceRunInitMsg,
    WorkspaceRunOverviewPreloadedMsg,
};
use crate::picture::PictureCmd;

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
    /// The OSC 11 answer captured at startup; `None` in test mode or when
    /// the terminal did not reply.
    background_is_dark: Option<bool>,
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
            background_is_dark: None,
            quit: false,
        }
    }

    pub fn quit_requested(&self) -> bool {
        self.quit
    }

    pub fn set_background_is_dark(&mut self, is_dark: Option<bool>) {
        self.background_is_dark = is_dark;
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
                if let Some(is_dark) = self.background_is_dark {
                    self.emit(Event::BackgroundColor { is_dark });
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
            Command::Picture(PictureCmd::Render(_request)) => {
                // PHASE-7: run KittyRenderRequest on an effect thread and
                // route the KittyFrameMsg (the glyph renderer — always
                // active in test mode — never issues renders).
                tracing::debug!("PictureCmd::Render not yet routed (PHASE-7)");
            }
            Command::RequestCellSize | Command::QueryKittySupport => {
                // PHASE-7: CSI 16 t / Kitty a=q probes need reply decoding
                // in the input path. Suppressed in test mode by the pane
                // (mediapane.go:180), so nothing is lost yet.
                tracing::debug!("terminal capability query not yet ported (PHASE-7)");
            }
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
// Background color detection (runtime only — never in test mode)
// ---------------------------------------------------------------------------

const BACKGROUND_QUERY_TIMEOUT: Duration = Duration::from_millis(500);

/// PARITY: mirrors `tea.RequestBackgroundColor` — Bubble Tea emits OSC 11
/// and its input loop decodes the reply into `tea.BackgroundColorMsg`. The
/// port performs one round-trip at startup, before the crossterm input
/// thread owns the tty (crossterm's parser would swallow the OSC reply).
/// A DA1 (`CSI c`) fence follows the query: terminals that ignore OSC 11
/// still answer DA1, bounding the read. No reply within the timeout → `None`
/// → no BackgroundColor event, exactly like a non-answering terminal in Go.
/// (If a terminal answers neither, the byte-reader thread stays parked on
/// the tty until one more byte arrives — accepted, DA1 support is
/// universal.)
///
/// In test mode this is never called: there are NO terminal queries and the
/// background is forced dark (light via `WANDB_LEET_TEST_BG=light`) through
/// `leet_charts::styles::default_dark_background()` (testmode.go).
pub(crate) fn detect_background_is_dark(timeout: Duration) -> Option<bool> {
    let mut tty = OpenOptions::new()
        .read(true)
        .write(true)
        .open("/dev/tty")
        .ok()?;
    tty.write_all(b"\x1b]11;?\x07\x1b[c").ok()?;
    tty.flush().ok()?;
    let mut reader = tty.try_clone().ok()?;

    let (tx, rx) = mpsc::channel::<u8>();
    let spawned = thread::Builder::new()
        .name("osc11-query".into())
        .spawn(move || {
            let mut seen: Vec<u8> = Vec::new();
            let mut byte = [0u8; 1];
            loop {
                match reader.read(&mut byte) {
                    Ok(0) | Err(_) => return,
                    Ok(_) => {
                        seen.push(byte[0]);
                        if tx.send(byte[0]).is_err() || contains_da1_reply(&seen) {
                            return;
                        }
                    }
                }
            }
        });
    spawned.ok()?;

    let deadline = Instant::now() + timeout;
    let mut buf: Vec<u8> = Vec::new();
    // Stops on the DA1 fence, on timeout, or when the reader hangs up.
    while let Ok(byte) = rx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
        buf.push(byte);
        if contains_da1_reply(&buf) {
            break;
        }
    }
    parse_osc11_is_dark(&buf)
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

/// Extracts the OSC 11 reply (`ESC ] 11 ; <color> BEL|ST`) and classifies
/// the color.
fn parse_osc11_is_dark(buf: &[u8]) -> Option<bool> {
    let s = String::from_utf8_lossy(buf);
    let start = s.find("\x1b]11;")? + 5;
    let rest = &s[start..];
    let end = rest.find(['\x07', '\x1b']).unwrap_or(rest.len());
    let (r, g, b) = parse_x_color(rest[..end].trim())?;
    Some(is_dark_color(r, g, b))
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
        )?;
        Terminal::new(CrosstermBackend::new(stdout))
    };
    // A failure after enable_raw_mode must not leave the process printing
    // its error into a raw-mode (and possibly alt-screen) terminal: undo
    // everything best-effort. restore_terminal's leave-alt-screen is
    // harmless when EnterAlternateScreen was queued but never flushed.
    setup().inspect_err(|_| restore_terminal())
}

/// Best-effort restore, also invoked by the panic hook (§2.8): leave the
/// alt screen, disable raw mode + mouse capture, show the cursor.
pub fn restore_terminal() {
    let mut stdout = io::stdout();
    let _ = execute!(
        stdout,
        cursor::Show,
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
        // swallow any later OSC 11 reply, so re-querying on an alt+r
        // restart session could never succeed anyway.
        static BACKGROUND_IS_DARK: OnceLock<Option<bool>> = OnceLock::new();
        effects.set_background_is_dark(
            *BACKGROUND_IS_DARK.get_or_init(|| detect_background_is_dark(BACKGROUND_QUERY_TIMEOUT)),
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

    // -- Background color parsing ---------------------------------------------

    #[test]
    fn osc11_reply_parsing_and_darkness() {
        // xterm-style 16-bit reply, dark background, BEL-terminated,
        // followed by the DA1 fence reply.
        let reply = b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07\x1b[?65;1;9c";
        assert!(contains_da1_reply(reply));
        assert_eq!(parse_osc11_is_dark(reply), Some(true));

        // Light background, ST-terminated.
        let reply = b"\x1b]11;rgb:ffff/ffff/ffff\x1b\\";
        assert_eq!(parse_osc11_is_dark(reply), Some(false));

        // 2-digit components scale by their own width.
        let reply = b"\x1b]11;rgb:20/20/20\x07";
        assert_eq!(parse_osc11_is_dark(reply), Some(true));

        // #RRGGBB form.
        let reply = b"\x1b]11;#f0f0f0\x07";
        assert_eq!(parse_osc11_is_dark(reply), Some(false));

        // DA1-only reply (terminal ignored OSC 11): no answer.
        let reply = b"\x1b[?6c";
        assert!(contains_da1_reply(reply));
        assert_eq!(parse_osc11_is_dark(reply), None);

        // Garbage: no answer, no fence.
        assert!(!contains_da1_reply(b"hello"));
        assert_eq!(parse_osc11_is_dark(b"hello"), None);
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
