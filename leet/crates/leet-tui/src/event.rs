//! Port of `core/internal/leet/messages.go` — the `tea.Msg` taxonomy as one
//! [`Event`] enum (docs/CONCURRENCY.md §2.2): one variant per Go message
//! type, same names, plus the Bubble Tea runtime messages leet consumes
//! (`tea.KeyPressMsg`, `tea.Mouse*Msg`, `tea.WindowSizeMsg`,
//! `tea.BackgroundColorMsg`) wrapping the [`crate::key`] types, plus the
//! picture-pipeline messages (`uv.CellSizeEvent`, `uv.KittyGraphicsEvent`,
//! `picture.kittyProbeTickMsg`, `picture.KittyFrameMsg` — the
//! `picture.IsPictureMsg` set minus `applyKittyGridMsg`, whose grid apply
//! is synchronous in the port, see media_pane.rs `handle_picture_msg`).
//!
//! [`Event::ack_name`] returns Go's `%T` string for each variant. The
//! differential harness steps scenarios by matching Update-ack lines against
//! the oracle's type names (core/internal/leet/testmode.go writes
//! `u <seq> %T`; leet/harness/leet-harness/src/ack.rs matches fragments), so
//! the Rust app must report byte-identical strings.
//
// PHASE-4: `mediaPanePrepareMsg` (mediapane.go:248-251) is deliberately not a
// variant yet. CONCURRENCY.md §2.5 replaces its cap-1 self-notify channel
// with a `prepare_requested` flag on the media pane; the media-pane port adds
// the variant (ack name "leet.mediaPanePrepareMsg") if the prepare request
// still needs to round-trip through the event queue for ack parity.

use std::collections::HashMap;
use std::fmt;
use std::time::SystemTime;

use leet_charts::styles::Rgb;
use leet_data::media::MediaPoint;
use leet_proto::wandb_internal::{ConfigRecord, EnvironmentRecord, SummaryRecord};

use crate::key::{KeyEvent, MouseEvent, MouseKind};

/// A Go `error` value carried in a message.
///
/// Handlers do three things with these errors: format them for logs/status
/// (runhandlers.go:77-81 logs `%v` and stores `Err.Error()`), match the
/// `errRunRecordNotFound` sentinel and `os.IsNotExist`
/// (workspacedirwatcher.go:282-296, workspacehandlers.go:603). `kind` carries
/// exactly that discrimination.
// PHASE-5: producers (reader threads, dir watcher, preloader) classify their
// errors when the app shell is ported; until then only `Other` is built.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventError {
    pub kind: EventErrorKind,
    pub message: String,
}

/// The error classes leet distinguishes (see [`EventError`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum EventErrorKind {
    #[default]
    Other,
    /// Go `os.IsNotExist(err)`.
    NotExist,
    /// Go `errors.Is(err, errRunRecordNotFound)` (workspacedirwatcher.go).
    RunRecordNotFound,
}

impl EventError {
    pub fn new(kind: EventErrorKind, message: impl Into<String>) -> Self {
        EventError {
            kind,
            message: message.into(),
        }
    }

    /// Convenience for unclassified errors (the common case).
    pub fn other(message: impl Into<String>) -> Self {
        EventError::new(EventErrorKind::Other, message)
    }
}

impl fmt::Display for EventError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

/// Handle to the initialized history reader carried by [`InitMsg`] and
/// [`WorkspaceRunInitMsg`].
///
/// Go hands the `HistorySource` interface value to the model
/// (messages.go:76-78, :110-114). In the Rust design the reader owns its
/// file on a dedicated thread (CONCURRENCY.md §2.3); the model holds this
/// opaque id and reads via `Command::Read*` — the runtime's effect runner
/// maps the id to the reader thread's request queue (see
/// [`crate::command::SourceId`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct HistorySourceHandle {
    pub id: crate::command::SourceId,
}

/// Per-metric X/Y series carried by [`HistoryMsg`] (messages.go `MetricData`).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct MetricData {
    pub x: Vec<f64>,
    pub y: Vec<f64>,
}

/// HistoryMsg contains metrics data from a wandb history record.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct HistoryMsg {
    pub run_path: String,
    pub metrics: HashMap<String, MetricData>,
    pub media: HashMap<String, Vec<MediaPoint>>,
}

/// RunMsg contains data from the wandb run record.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct RunMsg {
    pub run_path: String,
    pub id: String,
    pub project: String,
    pub display_name: String,
    pub notes: String,
    pub tags: Vec<String>,
    /// Go `*spb.ConfigRecord` (nil-able pointer).
    pub config: Option<Box<ConfigRecord>>,
}

/// SummaryMsg contains summary data from the wandb run.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SummaryMsg {
    pub run_path: String,
    /// Go `[]*spb.SummaryRecord`; elements are never nil in practice.
    pub summary: Vec<SummaryRecord>,
}

/// SystemInfoMsg contains system/environment information.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SystemInfoMsg {
    pub run_path: String,
    /// Go `*spb.EnvironmentRecord` (nil-able pointer).
    pub record: Option<Box<EnvironmentRecord>>,
}

/// FileCompleteMsg indicates that the file has been completely read.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct FileCompleteMsg {
    pub exit_code: i32,
}

/// StatsMsg contains system metrics data from a wandb stats record.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct StatsMsg {
    pub run_path: String,
    /// Unix timestamp in seconds.
    pub timestamp: i64,
    /// metric name -> value
    pub metrics: HashMap<String, f64>,
}

/// ConsoleLogMsg carries a raw console output record to be assembled by
/// `RunConsoleLogs`. Produced by the reader from output_raw records.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConsoleLogMsg {
    pub run_path: String,
    pub text: String,
    pub is_stderr: bool,
    pub time: SystemTime,
}

impl Default for ConsoleLogMsg {
    fn default() -> Self {
        ConsoleLogMsg {
            run_path: String::new(),
            text: String::new(),
            is_stderr: false,
            // PARITY: Go's zero time.Time; timestamps always come from
            // record data, so the epoch stand-in is never rendered.
            time: SystemTime::UNIX_EPOCH,
        }
    }
}

/// ErrorMsg wraps an error.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ErrorMsg {
    pub err: EventError,
}

/// InitMsg contains the initialized history source.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct InitMsg {
    pub source: HistorySourceHandle,
}

/// BatchedRecordsMsg contains all messages read during a batch read.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct BatchedRecordsMsg {
    pub msgs: Vec<Event>,
}

/// ChunkedBatchMsg contains a chunk of messages with progress info.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ChunkedBatchMsg {
    pub msgs: Vec<Event>,
    /// Indicates if there are more chunks to read.
    pub has_more: bool,
    /// Number of records in this chunk.
    pub progress: isize,
}

/// WorkspaceRunInitMsg is emitted when a workspace run reader has been
/// initialized.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct WorkspaceRunInitMsg {
    pub run_key: String,
    pub run_path: String,
    pub reader: HistorySourceHandle,
}

/// WorkspaceChunkedBatchMsg wraps a ChunkedBatchMsg with the originating run
/// key.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct WorkspaceChunkedBatchMsg {
    pub run_key: String,
    pub batch: ChunkedBatchMsg,
}

/// WorkspaceBatchedRecordsMsg wraps a BatchedRecordsMsg with the originating
/// run key.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct WorkspaceBatchedRecordsMsg {
    pub run_key: String,
    pub batch: BatchedRecordsMsg,
}

/// WorkspaceFileChangedMsg is emitted when a watched workspace run's .wandb
/// file changes on disk.
///
/// It carries the run key so the workspace can refresh just that run.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct WorkspaceFileChangedMsg {
    pub run_key: String,
}

/// WorkspaceRunDirsMsg is emitted after polling the wandb directory.
///
/// `run_keys` contains the set of run directory names (e.g. "run-..." /
/// "offline-run-..."). If `err` is non-`None`, `run_keys` may be empty and
/// callers should treat the snapshot as unusable.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct WorkspaceRunDirsMsg {
    pub run_keys: Vec<String>,
    pub err: Option<EventError>,
}

/// WorkspaceRunOverviewPreloadedMsg is emitted when the workspace finishes
/// preloading the Run record for a run (used to populate the overview sidebar
/// for runs that haven't been selected/streamed yet).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct WorkspaceRunOverviewPreloadedMsg {
    pub run_key: String,
    /// Go `*RunMsg` (nil-able pointer).
    pub run: Option<Box<RunMsg>>,
    pub err: Option<EventError>,
}

/// WorkspaceInitErrMsg is emitted when a workspace run reader failed to
/// initialize. This keeps errors keyed to the specific run so the workspace
/// can recover cleanly.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct WorkspaceInitErrMsg {
    pub run_key: String,
    pub run_path: String,
    pub err: Option<EventError>,
}

/// The Kitty graphics response fields leet consumes (`uv.KittyGraphicsEvent`,
/// ultraviolet event.go:373-379).
///
/// PARITY: Go carries the full `kitty.Options` + payload; leet's only
/// consumer is `picture.recordKittyResponse`, which reads `Options.ID`
/// (kitty_capability.go:197-204) — the response is reduced to that id
/// before it enters the event queue (the `BackgroundColor` precedent).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct KittyGraphicsMsg {
    pub id: i64,
}

/// The `tea.Msg` taxonomy: one variant per Go message type in messages.go
/// (same names, `Msg` suffix dropped on the variant), plus the four Bubble
/// Tea runtime messages leet consumes.
#[derive(Debug, Clone, PartialEq)]
pub enum Event {
    /// [`HistoryMsg`].
    History(HistoryMsg),
    /// [`RunMsg`].
    Run(RunMsg),
    /// [`SummaryMsg`].
    Summary(SummaryMsg),
    /// [`SystemInfoMsg`].
    SystemInfo(SystemInfoMsg),
    /// FileChangedMsg indicates that the watched file has changed.
    FileChanged,
    /// [`FileCompleteMsg`].
    FileComplete(FileCompleteMsg),
    /// [`StatsMsg`].
    Stats(StatsMsg),
    /// [`ConsoleLogMsg`].
    ConsoleLog(ConsoleLogMsg),
    /// [`ErrorMsg`].
    Error(ErrorMsg),
    /// [`InitMsg`].
    Init(InitMsg),
    /// [`BatchedRecordsMsg`].
    BatchedRecords(BatchedRecordsMsg),
    /// [`ChunkedBatchMsg`].
    ChunkedBatch(ChunkedBatchMsg),
    /// HeartbeatMsg is sent periodically for live runs to ensure we don't
    /// miss data.
    Heartbeat,
    /// LeftSidebarAnimationMsg is sent during left sidebar animations.
    LeftSidebarAnimation,
    /// RightSidebarAnimationMsg is sent during right sidebar animations.
    RightSidebarAnimation,
    /// WorkspaceRunsAnimationMsg drives animation for the workspace left
    /// sidebar.
    WorkspaceRunsAnimation,
    /// WorkspaceRunOverviewAnimationMsg drives animation for the workspace
    /// right sidebar.
    WorkspaceRunOverviewAnimation,
    /// [`WorkspaceRunInitMsg`].
    WorkspaceRunInit(WorkspaceRunInitMsg),
    /// [`WorkspaceChunkedBatchMsg`].
    WorkspaceChunkedBatch(WorkspaceChunkedBatchMsg),
    /// [`WorkspaceBatchedRecordsMsg`].
    WorkspaceBatchedRecords(WorkspaceBatchedRecordsMsg),
    /// [`WorkspaceFileChangedMsg`].
    WorkspaceFileChanged(WorkspaceFileChangedMsg),
    /// [`WorkspaceRunDirsMsg`].
    WorkspaceRunDirs(WorkspaceRunDirsMsg),
    /// [`WorkspaceRunOverviewPreloadedMsg`].
    WorkspaceRunOverviewPreloaded(WorkspaceRunOverviewPreloadedMsg),
    /// [`WorkspaceInitErrMsg`].
    WorkspaceInitErr(WorkspaceInitErrMsg),
    /// ConsoleLogsPaneAnimationMsg drives animation for the run view console
    /// logs pane.
    ConsoleLogsPaneAnimation,
    /// WorkspaceConsoleLogsPaneAnimationMsg drives animation for the
    /// workspace console logs pane.
    WorkspaceConsoleLogsPaneAnimation,
    /// WorkspaceSystemMetricsPaneAnimationMsg drives animation for the
    /// workspace system metrics pane.
    WorkspaceSystemMetricsPaneAnimation,
    /// MetricsGridAnimationMsg drives animation for the run view metrics grid
    /// collapse/expand.
    MetricsGridAnimation,
    /// WorkspaceMetricsGridAnimationMsg drives animation for the workspace
    /// metrics grid.
    WorkspaceMetricsGridAnimation,
    /// MediaPaneAnimationMsg drives animation for the run view media pane.
    MediaPaneAnimation,
    /// WorkspaceMediaPaneAnimationMsg drives animation for the workspace
    /// media pane.
    WorkspaceMediaPaneAnimation,

    /// `uv.CellSizeEvent` — the terminal's reply to the CSI 16 t cell-size
    /// query (`CSI 6 ; height ; width t`), routed to the media panes
    /// (mediapane.go:1262-1264). Width/Height are pixels.
    CellSize { width: isize, height: isize },
    /// `uv.KittyGraphicsEvent` — the terminal's response to the Kitty
    /// `a=q` support probe ([`KittyGraphicsMsg`]).
    KittyGraphics(KittyGraphicsMsg),
    /// `picture.kittyProbeTickMsg` — the probe-timeout tick batched with
    /// the probe write (kitty_capability.go:84-87).
    KittyProbeTick,
    /// `picture.KittyFrameMsg` — a deferred Kitty render's result, fed back
    /// to the pane's picture models (picture/messages.go). Boxed: the frame
    /// carries the APC payload + placeholder grid.
    KittyFrame(Box<crate::picture::KittyFrameMsg>),

    /// `tea.KeyPressMsg`.
    Key(KeyEvent),
    /// `tea.MouseClickMsg` / `tea.MouseReleaseMsg` / `tea.MouseMotionMsg` /
    /// `tea.MouseWheelMsg`, distinguished by [`MouseEvent::kind`].
    Mouse(MouseEvent),
    /// `tea.WindowSizeMsg` (Width/Height are Go `int`).
    Resize { width: isize, height: isize },
    /// `tea.BackgroundColorMsg`.
    // PARITY: Go carries the full terminal background color; the model calls
    // IsDark() on it (model.go:157-159) and the runs-list zebra stripe
    // re-reads the SAME OSC 11 answer through termenv's separate query
    // (styles.go:55-84 `initTerminalBg`). The port performs ONE round-trip,
    // so the event carries both the dark/light classification and the raw
    // 8-bit RGB (`None` when the reply wasn't in termenv's accepted form —
    // Go's `termBgDetected == false`, i.e. the zebra fallback).
    BackgroundColor { is_dark: bool, rgb: Option<Rgb> },
}

impl Event {
    /// The Go `%T` name testmode.go writes in Update ack lines
    /// (`u <seq> <msgType>`). The harness matches these against the oracle's
    /// output, so every string must be byte-identical to the Go type name.
    pub fn ack_name(&self) -> &'static str {
        match self {
            Event::History(_) => "leet.HistoryMsg",
            Event::Run(_) => "leet.RunMsg",
            Event::Summary(_) => "leet.SummaryMsg",
            Event::SystemInfo(_) => "leet.SystemInfoMsg",
            Event::FileChanged => "leet.FileChangedMsg",
            Event::FileComplete(_) => "leet.FileCompleteMsg",
            Event::Stats(_) => "leet.StatsMsg",
            Event::ConsoleLog(_) => "leet.ConsoleLogMsg",
            Event::Error(_) => "leet.ErrorMsg",
            Event::Init(_) => "leet.InitMsg",
            Event::BatchedRecords(_) => "leet.BatchedRecordsMsg",
            Event::ChunkedBatch(_) => "leet.ChunkedBatchMsg",
            Event::Heartbeat => "leet.HeartbeatMsg",
            Event::LeftSidebarAnimation => "leet.LeftSidebarAnimationMsg",
            Event::RightSidebarAnimation => "leet.RightSidebarAnimationMsg",
            Event::WorkspaceRunsAnimation => "leet.WorkspaceRunsAnimationMsg",
            Event::WorkspaceRunOverviewAnimation => "leet.WorkspaceRunOverviewAnimationMsg",
            Event::WorkspaceRunInit(_) => "leet.WorkspaceRunInitMsg",
            Event::WorkspaceChunkedBatch(_) => "leet.WorkspaceChunkedBatchMsg",
            Event::WorkspaceBatchedRecords(_) => "leet.WorkspaceBatchedRecordsMsg",
            Event::WorkspaceFileChanged(_) => "leet.WorkspaceFileChangedMsg",
            Event::WorkspaceRunDirs(_) => "leet.WorkspaceRunDirsMsg",
            Event::WorkspaceRunOverviewPreloaded(_) => "leet.WorkspaceRunOverviewPreloadedMsg",
            Event::WorkspaceInitErr(_) => "leet.WorkspaceInitErrMsg",
            Event::ConsoleLogsPaneAnimation => "leet.ConsoleLogsPaneAnimationMsg",
            Event::WorkspaceConsoleLogsPaneAnimation => "leet.WorkspaceConsoleLogsPaneAnimationMsg",
            Event::WorkspaceSystemMetricsPaneAnimation => {
                "leet.WorkspaceSystemMetricsPaneAnimationMsg"
            }
            Event::MetricsGridAnimation => "leet.MetricsGridAnimationMsg",
            Event::WorkspaceMetricsGridAnimation => "leet.WorkspaceMetricsGridAnimationMsg",
            Event::MediaPaneAnimation => "leet.MediaPaneAnimationMsg",
            Event::WorkspaceMediaPaneAnimation => "leet.WorkspaceMediaPaneAnimationMsg",
            Event::CellSize { .. } => "uv.CellSizeEvent",
            Event::KittyGraphics(_) => "uv.KittyGraphicsEvent",
            Event::KittyProbeTick => "picture.kittyProbeTickMsg",
            Event::KittyFrame(_) => "picture.KittyFrameMsg",
            Event::Key(_) => "tea.KeyPressMsg",
            Event::Mouse(m) => match m.kind {
                MouseKind::Click => "tea.MouseClickMsg",
                MouseKind::Release => "tea.MouseReleaseMsg",
                MouseKind::Motion => "tea.MouseMotionMsg",
                MouseKind::Wheel => "tea.MouseWheelMsg",
            },
            Event::Resize { .. } => "tea.WindowSizeMsg",
            Event::BackgroundColor { .. } => "tea.BackgroundColorMsg",
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use pretty_assertions::assert_eq;

    use super::*;
    use crate::key::{KeyCode, KeyMods, MouseButton};

    fn key_event() -> KeyEvent {
        KeyEvent {
            code: KeyCode::Char('q'),
            text: Some("q".into()),
            mods: KeyMods::NONE,
        }
    }

    fn mouse_event(kind: MouseKind) -> MouseEvent {
        MouseEvent {
            kind,
            button: MouseButton::Left,
            x: 0,
            y: 0,
            mods: KeyMods::NONE,
        }
    }

    /// One sample per variant, in messages.go declaration order, then the
    /// tea wrappers (Mouse repeated once per Go mouse message type).
    fn sample_events() -> Vec<Event> {
        vec![
            Event::History(HistoryMsg::default()),
            Event::Run(RunMsg::default()),
            Event::Summary(SummaryMsg::default()),
            Event::SystemInfo(SystemInfoMsg::default()),
            Event::FileChanged,
            Event::FileComplete(FileCompleteMsg::default()),
            Event::Stats(StatsMsg::default()),
            Event::ConsoleLog(ConsoleLogMsg::default()),
            Event::Error(ErrorMsg {
                err: EventError::other("boom"),
            }),
            Event::Init(InitMsg::default()),
            Event::BatchedRecords(BatchedRecordsMsg::default()),
            Event::ChunkedBatch(ChunkedBatchMsg::default()),
            Event::Heartbeat,
            Event::LeftSidebarAnimation,
            Event::RightSidebarAnimation,
            Event::WorkspaceRunsAnimation,
            Event::WorkspaceRunOverviewAnimation,
            Event::WorkspaceRunInit(WorkspaceRunInitMsg::default()),
            Event::WorkspaceChunkedBatch(WorkspaceChunkedBatchMsg::default()),
            Event::WorkspaceBatchedRecords(WorkspaceBatchedRecordsMsg::default()),
            Event::WorkspaceFileChanged(WorkspaceFileChangedMsg::default()),
            Event::WorkspaceRunDirs(WorkspaceRunDirsMsg::default()),
            Event::WorkspaceRunOverviewPreloaded(WorkspaceRunOverviewPreloadedMsg::default()),
            Event::WorkspaceInitErr(WorkspaceInitErrMsg::default()),
            Event::ConsoleLogsPaneAnimation,
            Event::WorkspaceConsoleLogsPaneAnimation,
            Event::WorkspaceSystemMetricsPaneAnimation,
            Event::MetricsGridAnimation,
            Event::WorkspaceMetricsGridAnimation,
            Event::MediaPaneAnimation,
            Event::WorkspaceMediaPaneAnimation,
            Event::CellSize {
                width: 10,
                height: 20,
            },
            Event::KittyGraphics(KittyGraphicsMsg::default()),
            Event::KittyProbeTick,
            Event::KittyFrame(Box::default()),
            Event::Key(key_event()),
            Event::Mouse(mouse_event(MouseKind::Click)),
            Event::Mouse(mouse_event(MouseKind::Release)),
            Event::Mouse(mouse_event(MouseKind::Motion)),
            Event::Mouse(mouse_event(MouseKind::Wheel)),
            Event::Resize {
                width: 120,
                height: 40,
            },
            Event::BackgroundColor {
                is_dark: true,
                rgb: None,
            },
        ]
    }

    /// Table extracted from the messages.go type declarations plus the tea
    /// message types leet consumes — exactly what Go's `%T` prints for each
    /// (testmode.go testAckUpdate).
    #[test]
    fn ack_names_match_go_type_names() {
        let want = vec![
            "leet.HistoryMsg",
            "leet.RunMsg",
            "leet.SummaryMsg",
            "leet.SystemInfoMsg",
            "leet.FileChangedMsg",
            "leet.FileCompleteMsg",
            "leet.StatsMsg",
            "leet.ConsoleLogMsg",
            "leet.ErrorMsg",
            "leet.InitMsg",
            "leet.BatchedRecordsMsg",
            "leet.ChunkedBatchMsg",
            "leet.HeartbeatMsg",
            "leet.LeftSidebarAnimationMsg",
            "leet.RightSidebarAnimationMsg",
            "leet.WorkspaceRunsAnimationMsg",
            "leet.WorkspaceRunOverviewAnimationMsg",
            "leet.WorkspaceRunInitMsg",
            "leet.WorkspaceChunkedBatchMsg",
            "leet.WorkspaceBatchedRecordsMsg",
            "leet.WorkspaceFileChangedMsg",
            "leet.WorkspaceRunDirsMsg",
            "leet.WorkspaceRunOverviewPreloadedMsg",
            "leet.WorkspaceInitErrMsg",
            "leet.ConsoleLogsPaneAnimationMsg",
            "leet.WorkspaceConsoleLogsPaneAnimationMsg",
            "leet.WorkspaceSystemMetricsPaneAnimationMsg",
            "leet.MetricsGridAnimationMsg",
            "leet.WorkspaceMetricsGridAnimationMsg",
            "leet.MediaPaneAnimationMsg",
            "leet.WorkspaceMediaPaneAnimationMsg",
            "uv.CellSizeEvent",
            "uv.KittyGraphicsEvent",
            "picture.kittyProbeTickMsg",
            "picture.KittyFrameMsg",
            "tea.KeyPressMsg",
            "tea.MouseClickMsg",
            "tea.MouseReleaseMsg",
            "tea.MouseMotionMsg",
            "tea.MouseWheelMsg",
            "tea.WindowSizeMsg",
            "tea.BackgroundColorMsg",
        ];
        let got: Vec<&str> = sample_events().iter().map(Event::ack_name).collect();
        assert_eq!(got, want);
    }

    /// messages.go declares 31 message types; the enum adds the four
    /// picture-pipeline messages (CellSize/KittyGraphics/KittyProbeTick/
    /// KittyFrame) and the four tea wrappers (Key/Mouse/Resize/
    /// BackgroundColor) — 39 variants total.
    #[test]
    fn one_variant_per_go_msg_type() {
        let discriminants: HashSet<_> =
            sample_events().iter().map(std::mem::discriminant).collect();
        assert_eq!(discriminants.len(), 31 + 4 + 4);
    }

    /// Events cross thread boundaries (producer threads → the event loop's
    /// mpsc channel, CONCURRENCY.md §2.1).
    #[test]
    fn event_is_send() {
        fn assert_send<T: Send>() {}
        assert_send::<Event>();
    }
}
