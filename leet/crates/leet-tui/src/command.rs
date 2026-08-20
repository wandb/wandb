//! The `tea.Cmd` surface of `core/internal/leet` as data: one [`Command`]
//! variant per command shape the Go app produces, executed by the runtime's
//! effect runner (docs/CONCURRENCY.md §2.7). Also home of the reader-thread
//! request protocol (§2.3) and the watcher-pump handle (§2.5).
//!
//! Go returns opaque `tea.Cmd` closures; the port names each closure shape.
//! `tea.Batch(cmds...)` → `Vec<Command>` in the same order. Two Go shapes
//! deliberately have NO variant:
//!
//!   - the consumed-key marker `func() tea.Msg { return nil }`
//!     (runhandlers.go:625) — returning no command (§2.7);
//!   - the pump commands `Workspace.waitForLiveMsg` (workspacehandlers.go:520)
//!     and `WatcherManager.WaitForMsg`'s heartbeat leg — C1/C2 disappear:
//!     heartbeats go scheduler → main channel directly (§2.5). There is also
//!     no `Restart` command: Go restarts via `tea.Quit` + the
//!     `Model.shouldRestart` flag (model.go:353-364), which ports as
//!     [`Command::Quit`] + `App::should_restart`.

use std::fmt;
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime};

use leet_data::history_source::{self as hs, HistorySource, SourceMsg};
use leet_data::remote::RemoteRunParams;

use crate::event::{
    BatchedRecordsMsg, ChunkedBatchMsg, ConsoleLogMsg, ErrorMsg, Event, EventError,
    FileCompleteMsg, HistoryMsg, MetricData, RunMsg, StatsMsg, SummaryMsg, SystemInfoMsg,
    WorkspaceBatchedRecordsMsg, WorkspaceChunkedBatchMsg,
};
use crate::picture::PictureCmd;

// ---------------------------------------------------------------------------
// Reader-thread handle (CONCURRENCY.md §2.3)
// ---------------------------------------------------------------------------

/// Identifies a reader thread: one per open `.wandb` file / remote source.
///
/// Go hands `HistorySource` interface values around (messages.go:76-78);
/// in the Rust design the reader owns its file exclusively on a dedicated
/// thread and the model holds this opaque id (inside
/// [`crate::event::HistorySourceHandle`]). The runtime's effect runner maps
/// the id to the thread's `mpsc::Sender<ReadRequest>`; dropping that sender
/// ends the thread (Go `historySource.Close()`, §2.9).
///
/// `SourceId(0)` is the `Default` placeholder and is never allocated
/// (Go's nil source).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct SourceId(pub u64);

/// A read request queued to a reader thread. `chunk_size` /
/// `max_time_per_chunk` mirror `HistorySource.Read`'s arguments
/// (historysource.go:39-42); [`ReadKind`] records which Go cmd body issued
/// the request and therefore how the result is wrapped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReadRequest {
    pub kind: ReadKind,
    pub chunk_size: usize,
    pub max_time_per_chunk: Duration,
}

/// Which Go read-cmd closure a [`ReadRequest`] ports; decides result
/// wrapping in [`execute_read`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReadKind {
    /// runhandlers.go:801 `readChunkCmd` — boot-load chunk for the run view.
    Chunk,
    /// runhandlers.go:820 `ReadLiveBatchCmd` — live drain for the run view.
    LiveBatch,
    /// workspacehandlers.go:459 `readAllChunkCmd` — boot-load chunk for a
    /// workspace run.
    WorkspaceChunk { run_key: String },
    /// workspacehandlers.go:486 `ReadAvailableCmd` — live drain for a
    /// workspace run.
    WorkspaceAvailable { run_key: String },
}

/// Executes one read and wraps the result exactly as the issuing Go cmd body
/// does. Runs ON the reader thread; the returned event (if any) is sent into
/// the main channel. `None` ⇔ the Go closure returning a nil `tea.Msg`.
///
/// PARITY: the four Go bodies call `source.Read` directly — NOT
/// `ReadRecords` (historysource.go:49), which is uncalled outside tests —
/// so the test-mode 24h chunk-time override in `read_records` does not
/// apply on the app's read path. Chunk boundaries are (count, wall-time)
/// bounded in test mode too, exactly like Go.
pub fn execute_read(source: &mut dyn HistorySource, req: ReadRequest) -> Option<Event> {
    let (msg, err) = source.read(req.chunk_size, req.max_time_per_chunk);
    // Go: `if err != nil && !errors.Is(err, io.EOF) { return ErrorMsg{Err: err} }`
    // — the error REPLACES the message.
    if let Some(err) = err
        && !err.is_eof()
    {
        return Some(Event::Error(ErrorMsg {
            err: EventError::other(err.to_string()),
        }));
    }
    let msg = msg?;
    match req.kind {
        ReadKind::Chunk => Some(source_msg_to_event(msg)),
        ReadKind::LiveBatch => match msg {
            SourceMsg::ChunkedBatch(batch) => {
                if batch.msgs.is_empty() {
                    return None;
                }
                Some(Event::BatchedRecords(BatchedRecordsMsg {
                    msgs: batch.msgs.into_iter().map(source_msg_to_event).collect(),
                }))
            }
            // Go: `if !ok { return msg }`.
            other => Some(source_msg_to_event(other)),
        },
        ReadKind::WorkspaceChunk { run_key } => match msg {
            SourceMsg::ChunkedBatch(batch) => {
                Some(Event::WorkspaceChunkedBatch(WorkspaceChunkedBatchMsg {
                    run_key,
                    batch: chunked_batch_to_event(batch),
                }))
            }
            // PARITY: errors (and any non-batch msg) pass through un-keyed,
            // as in Go readAllChunkCmd.
            other => Some(source_msg_to_event(other)),
        },
        ReadKind::WorkspaceAvailable { run_key } => match msg {
            SourceMsg::ChunkedBatch(batch) => {
                if batch.msgs.is_empty() {
                    return None;
                }
                Some(Event::WorkspaceBatchedRecords(WorkspaceBatchedRecordsMsg {
                    run_key,
                    batch: BatchedRecordsMsg {
                        msgs: batch.msgs.into_iter().map(source_msg_to_event).collect(),
                    },
                }))
            }
            other => Some(source_msg_to_event(other)),
        },
    }
}

/// Converts a data-layer [`SourceMsg`] into the app [`Event`] it is in Go
/// (Go has one set of message types; the port splits them between leet-data
/// and leet-tui, see leet-data/src/history_source.rs).
pub fn source_msg_to_event(msg: SourceMsg) -> Event {
    match msg {
        SourceMsg::History(m) => Event::History(HistoryMsg {
            run_path: m.run_path,
            metrics: m
                .metrics
                .into_iter()
                .map(|(k, v)| (k, MetricData { x: v.x, y: v.y }))
                .collect(),
            media: m.media,
        }),
        SourceMsg::Run(m) => Event::Run(run_msg_to_event(m)),
        SourceMsg::Summary(m) => Event::Summary(SummaryMsg {
            run_path: m.run_path,
            summary: m.summary,
        }),
        // PARITY: Go's *spb.EnvironmentRecord pointer is always non-nil when
        // produced by the reader (leveldbhistorysource.go recordToMsg).
        SourceMsg::SystemInfo(m) => Event::SystemInfo(SystemInfoMsg {
            run_path: m.run_path,
            record: Some(Box::new(m.record)),
        }),
        SourceMsg::Stats(m) => Event::Stats(StatsMsg {
            run_path: m.run_path,
            timestamp: m.timestamp,
            metrics: m.metrics,
        }),
        SourceMsg::ConsoleLog(m) => Event::ConsoleLog(ConsoleLogMsg {
            run_path: m.run_path,
            text: m.text,
            is_stderr: m.is_stderr,
            // PARITY: leet-data's None ⇔ Go's zero time.Time; the event
            // struct uses UNIX_EPOCH as that stand-in (see event.rs).
            time: m.time.unwrap_or(SystemTime::UNIX_EPOCH),
        }),
        SourceMsg::FileComplete(m) => Event::FileComplete(FileCompleteMsg {
            exit_code: m.exit_code,
        }),
        SourceMsg::ChunkedBatch(b) => Event::ChunkedBatch(chunked_batch_to_event(b)),
        SourceMsg::Error(e) => Event::Error(ErrorMsg {
            err: EventError::other(e.err.to_string()),
        }),
    }
}

/// [`source_msg_to_event`] for the `RunMsg` payload (also used by the
/// run-overview preloader, workspacedirwatcher.go FindRunMsg).
pub fn run_msg_to_event(m: hs::RunMsg) -> RunMsg {
    RunMsg {
        run_path: m.run_path,
        id: m.id,
        project: m.project,
        display_name: m.display_name,
        notes: m.notes,
        tags: m.tags,
        config: m.config.map(Box::new),
    }
}

/// [`source_msg_to_event`] for a whole chunked batch.
pub fn chunked_batch_to_event(b: hs::ChunkedBatchMsg) -> ChunkedBatchMsg {
    ChunkedBatchMsg {
        msgs: b.msgs.into_iter().map(source_msg_to_event).collect(),
        has_more: b.has_more,
        progress: b.progress as isize,
    }
}

// ---------------------------------------------------------------------------
// Timers (CONCURRENCY.md §2.4)
// ---------------------------------------------------------------------------

/// The scheduler's timer-wheel keys (CONCURRENCY.md §2.4).
/// `Arm` REPLACES any pending entry with the same id, which is what kills
/// Go's heartbeat generation counters (heartbeat.go:22).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum TimerId {
    /// T1 — heartbeat.go `time.AfterFunc` (15s default, config.go:56),
    /// keyed by the owning `HeartbeatManager` (see [`HeartbeatOwner`]).
    Heartbeat(HeartbeatOwner),
    /// T2 — workspacedirwatcher.go `wandbDirPollInterval` tick (5s).
    DirPoll,
    /// T4 — symon.go:532 `sampleLaterCmd` tick.
    // PHASE-6: fired ticks are ignored until the symon port lands.
    SymonSample,
    /// T3 — the 11 `tea.Tick(AnimationFrame, ..)` animation chains.
    Anim(AnimTarget),
    /// The Kitty probe-timeout tick — `tea.Tick(kittyProbeTimeout, ..)`
    /// batched with the probe write (kitty_capability.go:132-137). Fires
    /// `Event::KittyProbeTick`.
    KittyProbe,
}

/// Which model owns a heartbeat timer.
///
/// DIVERGENCE(CONCURRENCY.md §2.4): the doc prescribes a single `Heartbeat`
/// wheel key, but the Go spec runs TWO independent `HeartbeatManager`s
/// concurrently: `Run.heartbeatMgr` (run.go:159) and `Workspace.heartbeatMgr`
/// (workspace.go:176) are both live whenever the user is in run view —
/// model.go's `updateSubComponents` keeps the workspace's watchers/heartbeats
/// alive from there. With one key and arm-replaces-entry semantics each
/// view's Start/Reset would clobber the other's pending deadline and any Stop
/// would cancel both: e.g. viewing a FINISHED run while other workspace runs
/// are live, the run's `handleHeartbeat` stops its own manager on every fire
/// (runhandlers.go:931-934), which as a shared `Cancel(Heartbeat)` would
/// permanently kill the workspace's heartbeat safety net (and workspace Stop
/// sites — workspace.go:906-907, workspacehandlers.go:672/726/734 — would
/// kill the run view's). Owner-keyed ids (analogous to [`TimerId::Anim`])
/// keep the two timers independent, exactly like the two Go managers; both
/// fire the same payload-less `leet.HeartbeatMsg`, preserving Go's
/// two-HeartbeatMsg-per-interval ack counts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum HeartbeatOwner {
    /// `Run.heartbeatMgr` (run.go:159).
    Run,
    /// `Workspace.heartbeatMgr` (workspace.go:176).
    Workspace,
}

/// One variant per animation message (CONCURRENCY.md §2.4: "AnimTarget = 11
/// variants, one per animation msg"), in messages.go declaration order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum AnimTarget {
    /// runhandlers.go:688 (left sidebar `animationCmd`).
    LeftSidebar,
    /// rightsidebar.go:307.
    RightSidebar,
    /// workspace.go:809 `runsAnimationCmd`.
    WorkspaceRuns,
    /// workspace.go:816 `runOverviewAnimationCmd` (also
    /// runoverviewsidebar.go:283).
    WorkspaceRunOverview,
    /// runhandlers.go:796 `consoleLogsPaneAnimationCmd`.
    ConsoleLogsPane,
    /// workspace.go:822.
    WorkspaceConsoleLogsPane,
    /// workspace.go:840 `systemMetricsPaneAnimationCmd`.
    WorkspaceSystemMetricsPane,
    /// runhandlers.go:562 `metricsGridAnimationCmd`.
    MetricsGrid,
    /// workspace.go:834.
    WorkspaceMetricsGrid,
    /// runhandlers.go:752 `mediaPaneAnimationCmd`.
    MediaPane,
    /// workspace.go:828.
    WorkspaceMediaPane,
}

impl AnimTarget {
    pub const ALL: [AnimTarget; 11] = [
        AnimTarget::LeftSidebar,
        AnimTarget::RightSidebar,
        AnimTarget::WorkspaceRuns,
        AnimTarget::WorkspaceRunOverview,
        AnimTarget::ConsoleLogsPane,
        AnimTarget::WorkspaceConsoleLogsPane,
        AnimTarget::WorkspaceSystemMetricsPane,
        AnimTarget::MetricsGrid,
        AnimTarget::WorkspaceMetricsGrid,
        AnimTarget::MediaPane,
        AnimTarget::WorkspaceMediaPane,
    ];

    /// The animation message this timer delivers when it fires — the return
    /// value of the Go `tea.Tick` callback at the corresponding call site.
    pub fn event(self) -> Event {
        match self {
            AnimTarget::LeftSidebar => Event::LeftSidebarAnimation,
            AnimTarget::RightSidebar => Event::RightSidebarAnimation,
            AnimTarget::WorkspaceRuns => Event::WorkspaceRunsAnimation,
            AnimTarget::WorkspaceRunOverview => Event::WorkspaceRunOverviewAnimation,
            AnimTarget::ConsoleLogsPane => Event::ConsoleLogsPaneAnimation,
            AnimTarget::WorkspaceConsoleLogsPane => Event::WorkspaceConsoleLogsPaneAnimation,
            AnimTarget::WorkspaceSystemMetricsPane => Event::WorkspaceSystemMetricsPaneAnimation,
            AnimTarget::MetricsGrid => Event::MetricsGridAnimation,
            AnimTarget::WorkspaceMetricsGrid => Event::WorkspaceMetricsGridAnimation,
            AnimTarget::MediaPane => Event::MediaPaneAnimation,
            AnimTarget::WorkspaceMediaPane => Event::WorkspaceMediaPaneAnimation,
        }
    }

    /// Inverse of [`AnimTarget::event`]: the panes' `update` methods return
    /// the animation [`Event`] to schedule (e.g. right_sidebar.rs); the
    /// model maps it back to the timer to arm.
    pub fn for_event(event: &Event) -> Option<AnimTarget> {
        match event {
            Event::LeftSidebarAnimation => Some(AnimTarget::LeftSidebar),
            Event::RightSidebarAnimation => Some(AnimTarget::RightSidebar),
            Event::WorkspaceRunsAnimation => Some(AnimTarget::WorkspaceRuns),
            Event::WorkspaceRunOverviewAnimation => Some(AnimTarget::WorkspaceRunOverview),
            Event::ConsoleLogsPaneAnimation => Some(AnimTarget::ConsoleLogsPane),
            Event::WorkspaceConsoleLogsPaneAnimation => Some(AnimTarget::WorkspaceConsoleLogsPane),
            Event::WorkspaceSystemMetricsPaneAnimation => {
                Some(AnimTarget::WorkspaceSystemMetricsPane)
            }
            Event::MetricsGridAnimation => Some(AnimTarget::MetricsGrid),
            Event::WorkspaceMetricsGridAnimation => Some(AnimTarget::WorkspaceMetricsGrid),
            Event::MediaPaneAnimation => Some(AnimTarget::MediaPane),
            Event::WorkspaceMediaPaneAnimation => Some(AnimTarget::WorkspaceMediaPane),
            _ => None,
        }
    }
}

// ---------------------------------------------------------------------------
// Watcher pump handle (CONCURRENCY.md §2.5)
// ---------------------------------------------------------------------------

/// The read side of a watcher registration's cap-1 notification channel.
///
/// The watcher thread (watcher_manager.rs) `try_send`s `()` on file change
/// and drops it when the slot is full — a burst of changes coalesces to one
/// notification (Go C3, workspacehandlers.go:541 / watchermanager.go:42-47).
/// The pump commands ([`Command::AwaitWatcherMsg`] /
/// [`Command::AwaitWorkspaceWatcher`]) do ONE `recv` each and are re-armed
/// by the handler. Unregistering drops the `SyncSender` → `recv` returns
/// `Err(Disconnected)` → the pump exits silently, replacing Go's nil-send
/// shutdown handshake (C4, watchermanager.go:70-74).
///
/// DIVERGENCE(CONCURRENCY.md §2.5): the doc prescribes crossbeam
/// `bounded(1)`, but crossbeam-channel is not a workspace dependency.
/// `std::sync::mpsc::sync_channel(1)` has the same `try_send`
/// (drop-on-full) and disconnect semantics; the std `Receiver` is not
/// `Clone`, so pumps share it behind `Arc<Mutex<..>>` — uncontended, since
/// at most one pump per registration is ever in flight (one-in-flight
/// delivery, §2.5). Same substitution precedent as the doc's media
/// `prepareCh` → plain flag.
#[derive(Clone)]
pub struct WatchReceiver(Arc<Mutex<mpsc::Receiver<()>>>);

impl WatchReceiver {
    /// Creates a registration channel: the watcher keeps the notify side,
    /// the model keeps the pump side.
    pub fn channel() -> (mpsc::SyncSender<()>, WatchReceiver) {
        let (tx, rx) = mpsc::sync_channel(1);
        (tx, WatchReceiver(Arc::new(Mutex::new(rx))))
    }

    /// One blocking receive: `Ok(())` = the file changed, `Err` = the
    /// registration was dropped (watcher finished).
    pub fn recv(&self) -> Result<(), mpsc::RecvError> {
        // A poisoned lock only means a previous pump panicked mid-recv;
        // the channel itself is still coherent.
        self.0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .recv()
    }
}

impl fmt::Debug for WatchReceiver {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("WatchReceiver")
    }
}

// ---------------------------------------------------------------------------
// Command (CONCURRENCY.md §2.7)
// ---------------------------------------------------------------------------

/// One variant per `tea.Cmd` shape the Go app produces. Blocking commands
/// run on effect/reader threads and send exactly one [`Event`] (§2.7);
/// timer commands go to the scheduler; the rest are runtime-local.
#[derive(Debug, Clone)]
pub enum Command {
    /// `tea.RequestBackgroundColor` (model.go:130, symon.go:106). The
    /// runtime replays the OSC 11 answer it captured at startup as
    /// `Event::BackgroundColor`; never emitted in test mode (model.go:126).
    RequestBackgroundColor,

    /// `InitializeLevelDBHistorySource` (leveldbhistorysource.go:52,
    /// issued run.go:187): spawn the reader thread; reply `Event::Init`
    /// or `Event::Error`.
    InitReader { run_path: String },

    /// `InitializeParquetHistorySource` (parquethistorysource.go:120,
    /// issued run.go:185).
    // PHASE-7: leet-remote; the effect runner logs-and-drops until then.
    InitRemoteReader { remote: RemoteRunParams },

    /// Workspace `initReaderCmd` (workspacehandlers.go:440): spawn the
    /// reader thread; reply `Event::WorkspaceRunInit` or
    /// `Event::WorkspaceInitErr`.
    InitWorkspaceReader { run_key: String, run_path: String },

    /// `readChunkCmd` (runhandlers.go:801) — the caller passes the same
    /// (chunkSize, maxTime) Go passes (BootLoad* at runhandlers.go:874/894).
    ReadChunk {
        source: SourceId,
        chunk_size: usize,
        max_time_per_chunk: Duration,
    },

    /// `ReadLiveBatchCmd` (runhandlers.go:820); LiveMonitor* bounds are
    /// baked into the body like Go.
    ReadLiveBatch { source: SourceId },

    /// Workspace `readAllChunkCmd` (workspacehandlers.go:459); BootLoad*
    /// bounds baked in.
    ReadAllChunk { source: SourceId, run_key: String },

    /// Workspace `ReadAvailableCmd` (workspacehandlers.go:486);
    /// LiveMonitor* bounds baked in.
    ReadAvailable { source: SourceId, run_key: String },

    /// `historySource.Close()` (runhandlers.go:346, workspace.go:365):
    /// drops the reader's request sender; the thread closes the file and
    /// exits (§2.9).
    CloseReader { source: SourceId },

    /// `WatcherManager.WaitForMsg` pump (watchermanager.go:83): one `recv`
    /// → `Event::FileChanged`. Armed after boot load (runhandlers.go:908)
    /// and re-armed per handled file change (runhandlers.go:950) ONLY.
    ///
    /// Go has a third re-arm site, runhandlers.go:938 (`handleHeartbeat`)
    /// — valid there because the pump just returned: it delivered the
    /// `HeartbeatMsg` from the shared C1 chan. Here heartbeats bypass the
    /// pump (scheduler → main channel; see the module header's "no variant"
    /// note and §2.5), so on a heartbeat the pump is still blocked on the
    /// watcher receiver — re-issuing this command there would stack one
    /// extra pump thread on the same registration per heartbeat fire.
    /// Phase 5b must NOT port :938 as an arm site. (CONCURRENCY.md §2.5
    /// repeats the 908/938/950 list without this caveat.)
    AwaitWatcherMsg { rx: WatchReceiver },

    /// Workspace `waitForWatcher` pump (workspacehandlers.go:566; armed
    /// :549/:761): one `recv` → `Event::WorkspaceFileChanged{run_key}`.
    AwaitWorkspaceWatcher { run_key: String, rx: WatchReceiver },

    /// Every `tea.Tick(d, ..)` call site and heartbeat (re)arm →
    /// `TimerCmd::Arm(id, duration)`; replaces any pending entry (§2.4).
    Tick { id: TimerId, duration: Duration },

    /// `HeartbeatManager.Stop` (heartbeat.go:107) and friends →
    /// `TimerCmd::Cancel(id)`.
    CancelTimer { id: TimerId },

    /// `pollWandbDirCmd` (workspacedirwatcher.go:100): arm
    /// `TimerId::DirPoll`; on fire the runtime runs the dir scan on an
    /// effect thread (the Go tick callback body) → `Event::WorkspaceRunDirs`.
    PollWandbDir { wandb_dir: String, delay: Duration },

    /// `preloadRunOverviewCmd` (workspacedirwatcher.go:225): open, scan up
    /// to 10 records for the Run record, close →
    /// `Event::WorkspaceRunOverviewPreloaded`. Bounded concurrency (B4) is
    /// enforced by the model's preloader queue, which caps in-flight
    /// commands at 4.
    PreloadRunOverview { run_key: String, wandb_file: String },

    /// A Go cmd that immediately returns a message, e.g. the synthetic
    /// `tea.WindowSizeMsg` on run-view entry (model.go:404-407): re-enqueue
    /// the event.
    Emit(Box<Event>),

    /// Picture-model commands from the media pane (`MediaPaneCmd::Picture`):
    /// `tea.Raw` Kitty byte writes and deferred Kitty renders
    /// (mediapane.go:1420, picture.rs). `Render` runs on an effect thread
    /// and feeds the frame back as `Event::KittyFrame` (the glyph renderer
    /// — always active in test mode — never issues renders).
    Picture(PictureCmd),

    /// `picture.RequestCellSize()` — the CSI 16 t query (mediapane.go:187).
    /// Suppressed in test mode (mediapane.go:180). The query bytes went to
    /// the terminal during the runtime's startup round-trip; dispatch
    /// replays the captured reply as `Event::CellSize` (see runtime.rs
    /// `detect_terminal_capabilities`).
    RequestCellSize,

    /// `picture.QueryKittySupport()` — the Kitty `a=q` probe
    /// (mediapane.go:188, kitty_capability.go:116-140). Suppressed in test
    /// mode. Once per process; resolves through `Event::KittyGraphics` /
    /// `Event::KittyProbeTick` (see runtime.rs).
    QueryKittySupport,

    /// `sampleNowCmd` (symon.go:516): run one sampling pass off-thread.
    // PHASE-6: symon sampler.
    SampleSymonNow,

    /// `tea.Quit`: the loop breaks; quit paths have already run their own
    /// cleanup (runhandlers.go:349-354, workspacehandlers.go:773-778).
    Quit,
}

impl Command {
    /// Convenience for the 11 animation `tea.Tick(AnimationFrame, ..)`
    /// call sites (§2.4): arm the target's frame timer.
    pub fn tick_anim(target: AnimTarget) -> Command {
        Command::Tick {
            id: TimerId::Anim(target),
            duration: leet_charts::styles::ANIMATION_FRAME,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::sync::mpsc::TrySendError;

    use pretty_assertions::assert_eq;

    use super::*;
    use leet_data::history_source::HistorySourceError;

    // -- AnimTarget <-> Event mapping ---------------------------------------

    /// CONCURRENCY.md §2.4: 11 animation targets, one per animation msg;
    /// `event()`/`for_event` must be exact inverses.
    #[test]
    fn anim_target_event_round_trip() {
        assert_eq!(AnimTarget::ALL.len(), 11);
        let distinct: HashSet<_> = AnimTarget::ALL
            .iter()
            .map(|t| std::mem::discriminant(&t.event()))
            .collect();
        assert_eq!(distinct.len(), 11);
        for target in AnimTarget::ALL {
            assert_eq!(AnimTarget::for_event(&target.event()), Some(target));
        }
        assert_eq!(AnimTarget::for_event(&Event::Heartbeat), None);
    }

    /// The animation tick helper arms the frame timer with Go's
    /// `AnimationFrame` (styles.go:785).
    #[test]
    fn tick_anim_uses_animation_frame() {
        let Command::Tick { id, duration } = Command::tick_anim(AnimTarget::MediaPane) else {
            panic!("expected Tick");
        };
        assert_eq!(id, TimerId::Anim(AnimTarget::MediaPane));
        assert_eq!(duration, leet_charts::styles::ANIMATION_FRAME);
    }

    // -- WatchReceiver (cap-1 coalescing + disconnect, §2.5) -----------------

    #[test]
    fn watch_receiver_coalesces_to_one_notification() {
        let (tx, rx) = WatchReceiver::channel();
        // Burst of file changes: first try_send fills the slot, the rest
        // drop (watchermanager.go:42-47 select+default).
        tx.try_send(()).unwrap();
        assert!(matches!(tx.try_send(()), Err(TrySendError::Full(()))));
        assert!(matches!(tx.try_send(()), Err(TrySendError::Full(()))));
        // The pump drains exactly one notification.
        assert!(rx.recv().is_ok());
        // Dropping the notify side unblocks/ends the pump (replaces the C4
        // nil-send handshake).
        drop(tx);
        assert!(rx.recv().is_err());
    }

    // -- SourceMsg -> Event conversion ---------------------------------------

    fn chunked(msgs: Vec<SourceMsg>, has_more: bool, progress: usize) -> hs::ChunkedBatchMsg {
        hs::ChunkedBatchMsg {
            msgs,
            has_more,
            progress,
        }
    }

    #[test]
    fn source_msg_to_event_maps_each_variant() {
        let run = hs::RunMsg {
            run_path: "p".into(),
            id: "abc".into(),
            ..Default::default()
        };
        let got = source_msg_to_event(SourceMsg::Run(run));
        let Event::Run(run) = got else {
            panic!("expected Run");
        };
        assert_eq!(run.id, "abc");
        assert_eq!(run.config, None);

        let got = source_msg_to_event(SourceMsg::ConsoleLog(hs::ConsoleLogMsg {
            run_path: "p".into(),
            text: "hi".into(),
            is_stderr: true,
            time: None,
        }));
        let Event::ConsoleLog(log) = got else {
            panic!("expected ConsoleLog");
        };
        // None ⇔ Go's zero time.Time ⇔ the event struct's epoch stand-in.
        assert_eq!(log.time, SystemTime::UNIX_EPOCH);
        assert!(log.is_stderr);

        let got = source_msg_to_event(SourceMsg::ChunkedBatch(chunked(
            vec![SourceMsg::FileComplete(hs::FileCompleteMsg {
                exit_code: 7,
            })],
            true,
            41,
        )));
        let Event::ChunkedBatch(batch) = got else {
            panic!("expected ChunkedBatch");
        };
        assert_eq!(batch.progress, 41);
        assert!(batch.has_more);
        assert_eq!(
            batch.msgs,
            vec![Event::FileComplete(FileCompleteMsg { exit_code: 7 })]
        );

        let got = source_msg_to_event(SourceMsg::Error(hs::ErrorMsg { err: "boom".into() }));
        let Event::Error(err) = got else {
            panic!("expected Error");
        };
        assert_eq!(err.err.message, "boom");
    }

    // -- execute_read wrapping (the four Go cmd bodies) ----------------------

    /// A scripted source: returns the queued (msg, err) pairs in order.
    struct ScriptedSource {
        script: Vec<(Option<SourceMsg>, Option<HistorySourceError>)>,
    }

    impl HistorySource for ScriptedSource {
        fn read(
            &mut self,
            _chunk_size: usize,
            _max_time: Duration,
        ) -> (Option<SourceMsg>, Option<HistorySourceError>) {
            self.script.remove(0)
        }

        fn close(&mut self) {}
    }

    fn read_one(
        kind: ReadKind,
        msg: Option<SourceMsg>,
        err: Option<HistorySourceError>,
    ) -> Option<Event> {
        let mut source = ScriptedSource {
            script: vec![(msg, err)],
        };
        execute_read(
            &mut source,
            ReadRequest {
                kind,
                chunk_size: 10,
                max_time_per_chunk: Duration::from_millis(10),
            },
        )
    }

    // Go: TestReadLiveBatchCmd-style cases (liveread_test.go — the
    // runhandlers/workspacehandlers legs deferred from leet-data, see the
    // note in history_source.rs).
    #[test]
    fn execute_read_wraps_like_the_go_cmd_bodies() {
        // readChunkCmd: batch passes through as ChunkedBatch.
        let got = read_one(
            ReadKind::Chunk,
            Some(SourceMsg::ChunkedBatch(chunked(vec![], false, 0))),
            None,
        );
        assert!(matches!(got, Some(Event::ChunkedBatch(_))));

        // readChunkCmd: EOF alongside a batch is swallowed (boot-load end).
        let got = read_one(
            ReadKind::Chunk,
            Some(SourceMsg::ChunkedBatch(chunked(vec![], false, 0))),
            Some(HistorySourceError::Eof),
        );
        assert!(matches!(got, Some(Event::ChunkedBatch(_))));

        // Non-EOF error REPLACES the message with ErrorMsg.
        let got = read_one(
            ReadKind::Chunk,
            Some(SourceMsg::ChunkedBatch(chunked(vec![], false, 0))),
            Some(HistorySourceError::Other("bad".into())),
        );
        let Some(Event::Error(err)) = got else {
            panic!("expected Error, got {got:?}");
        };
        assert_eq!(err.err.message, "bad");

        // ReadLiveBatchCmd: empty batch → nil msg (no event).
        let got = read_one(
            ReadKind::LiveBatch,
            Some(SourceMsg::ChunkedBatch(chunked(vec![], true, 0))),
            None,
        );
        assert_eq!(got, None);

        // ReadLiveBatchCmd: non-empty batch → BatchedRecordsMsg.
        let got = read_one(
            ReadKind::LiveBatch,
            Some(SourceMsg::ChunkedBatch(chunked(
                vec![SourceMsg::History(hs::HistoryMsg::default())],
                true,
                1,
            ))),
            None,
        );
        let Some(Event::BatchedRecords(batch)) = got else {
            panic!("expected BatchedRecords, got {got:?}");
        };
        assert_eq!(batch.msgs.len(), 1);

        // readAllChunkCmd: batch gets the run key.
        let got = read_one(
            ReadKind::WorkspaceChunk {
                run_key: "run-1".into(),
            },
            Some(SourceMsg::ChunkedBatch(chunked(vec![], false, 3))),
            None,
        );
        let Some(Event::WorkspaceChunkedBatch(batch)) = got else {
            panic!("expected WorkspaceChunkedBatch, got {got:?}");
        };
        assert_eq!(batch.run_key, "run-1");
        assert_eq!(batch.batch.progress, 3);

        // ReadAvailableCmd: empty → nothing; non-empty → keyed batch.
        let got = read_one(
            ReadKind::WorkspaceAvailable {
                run_key: "run-1".into(),
            },
            Some(SourceMsg::ChunkedBatch(chunked(vec![], true, 0))),
            None,
        );
        assert_eq!(got, None);
        let got = read_one(
            ReadKind::WorkspaceAvailable {
                run_key: "run-1".into(),
            },
            Some(SourceMsg::ChunkedBatch(chunked(
                vec![SourceMsg::Stats(hs::StatsMsg::default())],
                true,
                1,
            ))),
            None,
        );
        let Some(Event::WorkspaceBatchedRecords(batch)) = got else {
            panic!("expected WorkspaceBatchedRecords, got {got:?}");
        };
        assert_eq!(batch.run_key, "run-1");
        assert_eq!(batch.batch.msgs.len(), 1);

        // Nil msg → no event (Go returns nil).
        assert_eq!(read_one(ReadKind::Chunk, None, None), None);
    }
}
