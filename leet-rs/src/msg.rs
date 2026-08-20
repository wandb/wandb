//! Messages passed from background readers/watchers to the UI loop.

use std::time::SystemTime;

use crate::store::proto::{ConfigRecord, EnvironmentRecord, SummaryRecord};

/// Points for one metric: parallel X/Y arrays.
#[derive(Debug, Clone, Default)]
pub struct MetricData {
    pub x: Vec<f64>,
    pub y: Vec<f64>,
}

/// A single logged media item (currently images).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct MediaPoint {
    pub x: f64,
    pub file_path: String,
    pub relative_path: String,
    pub caption: String,
    pub format: String,
    pub width: i32,
    pub height: i32,
    pub sha256: String,
}

/// Metrics + media extracted from history records.
#[derive(Debug, Clone, Default)]
pub struct HistoryMsg {
    pub run_path: String,
    pub metrics: Vec<(String, MetricData)>,
    pub media: Vec<(String, Vec<MediaPoint>)>,
}

/// Data from the wandb run record.
#[derive(Debug, Clone, Default)]
pub struct RunMsg {
    pub run_path: String,
    pub id: String,
    pub project: String,
    pub display_name: String,
    pub notes: String,
    pub tags: Vec<String>,
    pub config: Option<ConfigRecord>,
}

/// System metrics from a stats record.
#[derive(Debug, Clone, Default)]
pub struct StatsMsg {
    pub run_path: String,
    /// Unix timestamp in seconds.
    pub timestamp: i64,
    pub metrics: Vec<(String, f64)>,
}

/// A raw console output line.
#[derive(Debug, Clone)]
pub struct ConsoleLogMsg {
    pub run_path: String,
    pub text: String,
    pub is_stderr: bool,
    pub time: Option<SystemTime>,
}

/// One decoded record, already converted for UI consumption.
#[derive(Debug, Clone)]
pub enum RecordMsg {
    Run(RunMsg),
    History(HistoryMsg),
    Summary {
        run_path: String,
        summary: Vec<SummaryRecord>,
    },
    SystemInfo {
        run_path: String,
        record: Box<EnvironmentRecord>,
    },
    Stats(StatsMsg),
    ConsoleLog(ConsoleLogMsg),
    /// The exit record has been seen; the file is complete.
    FileComplete {
        exit_code: i32,
    },
}

/// Messages delivered to the UI event loop.
#[derive(Debug)]
pub enum Msg {
    /// A terminal input event forwarded by the input thread, giving the UI
    /// loop a single blocking wait point.
    Term(crossterm::event::Event),
    /// A chunk of records from a reader thread.
    Batch {
        /// Identifies the reader instance so stale messages can be dropped.
        source_id: u64,
        msgs: Vec<RecordMsg>,
        /// Number of records scanned in this chunk (boot progress).
        progress: usize,
        /// True once the reader finished the initial catch-up read.
        caught_up: bool,
    },
    /// A reader failed to initialize or hit an unrecoverable error.
    ReaderError { source_id: u64, error: String },
    /// New snapshot of run directories in the workspace.
    RunDirs { keys: Vec<String> },
    /// Preloaded run metadata for the workspace run list/overview.
    RunPreloaded {
        run_key: String,
        run: Option<Box<RunMsg>>,
    },
    /// A sample from the standalone system monitor.
    SymonSample(StatsMsg),
}
