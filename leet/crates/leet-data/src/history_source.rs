//! Port of `core/internal/leet/historysource.go` — the [`HistorySource`]
//! trait for reading W&B run history data — plus [`SourceMsg`], the
//! leet-data-owned subset of `messages.go`: the data-carrying tea.Msg types
//! produced by history sources. leet-tui's `Event` enum wraps these
//! (PORTING.md: `tea.Msg` → enum, one variant per Go msg type).
//!
//! PARITY: the remaining `messages.go` types (`InitMsg`, `BatchedRecordsMsg`,
//! `FileChangedMsg`, the animation/workspace messages, …) are produced and
//! consumed by leet-tui and port there with `model.go`/`messages.go`. In
//! particular `InitMsg{Source HistorySource}` carries a
//! `Box<dyn HistorySource>` and cannot live here without dragging command
//! plumbing into the data layer.

use std::collections::HashMap;
use std::time::{Duration, SystemTime};

use leet_proto::wandb_internal::{ConfigRecord, EnvironmentRecord, SummaryRecord};
use leet_wire::live_store::LiveStoreError;

use crate::media::MediaPoint;
use crate::test_mode;

// Boot loading parameters
pub const BOOT_LOAD_CHUNK_SIZE: usize = 1000;
pub const BOOT_LOAD_MAX_TIME: Duration = Duration::from_millis(100);

// Live monitoring parameters
pub const LIVE_MONITOR_CHUNK_SIZE: usize = 2000;
pub const LIVE_MONITOR_MAX_TIME: Duration = Duration::from_millis(50);

/// Go: `messages.go` MetricData.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct MetricData {
    pub x: Vec<f64>,
    pub y: Vec<f64>,
}

/// HistoryMsg contains metrics data from a wandb history record.
// PARITY: Go's Metrics/Media maps may be nil (ParseHistory leaves them unset
// when empty; concatenateHistory nils them out). Every reader only lens,
// ranges, or indexes them, so a nil map and an empty map are
// indistinguishable — ported as plain (empty) HashMaps.
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
    pub config: Option<ConfigRecord>,
}

/// SummaryMsg contains summary data from the wandb run.
// PARITY: Go holds []*spb.SummaryRecord; the records are owned values here
// (prost oneofs yield records by value, so the pointers are never nil).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SummaryMsg {
    pub run_path: String,
    pub summary: Vec<SummaryRecord>,
}

/// SystemInfoMsg contains system/environment information.
// PARITY: Go holds *spb.EnvironmentRecord; by value here (see SummaryMsg).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SystemInfoMsg {
    pub run_path: String,
    pub record: EnvironmentRecord,
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
    /// Unix timestamp in seconds
    pub timestamp: i64,
    /// metric name -> value
    pub metrics: HashMap<String, f64>,
}

/// ConsoleLogMsg carries a raw console output record to be assembled
/// by `RunConsoleLogs`. Produced by the reader from output_raw records.
// PARITY: Go's Time is a time.Time — the zero value when the record has no
// timestamp, time.Unix(seconds, nanos) otherwise. Ported as
// Option<SystemTime>: None ↔ the zero time.Time (renders as "00:00:00" in
// the console pane's "15:04:05" layout).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ConsoleLogMsg {
    pub run_path: String,
    pub text: String,
    pub is_stderr: bool,
    pub time: Option<SystemTime>,
}

/// ErrorMsg wraps an error.
// PARITY: Go wraps the open `error` interface; boxed dyn Error mirrors that.
#[derive(Debug)]
pub struct ErrorMsg {
    pub err: Box<dyn std::error::Error + Send + Sync>,
}

/// ChunkedBatchMsg contains a chunk of messages with progress info.
#[derive(Debug, Default)]
pub struct ChunkedBatchMsg {
    pub msgs: Vec<SourceMsg>,
    /// Indicates if there are more chunks to read
    pub has_more: bool,
    /// Number of records in this chunk
    pub progress: usize,
}

/// SourceMsg is a tea.Msg value produced by a history source
/// (`historysource.go` / `leveldbhistorysource.go`).
#[derive(Debug)]
pub enum SourceMsg {
    History(HistoryMsg),
    Run(RunMsg),
    Summary(SummaryMsg),
    // PARITY: boxed — EnvironmentRecord dwarfs the other variants (Go's
    // tea.Msg interface heap-boxes every message anyway).
    SystemInfo(Box<SystemInfoMsg>),
    Stats(StatsMsg),
    ConsoleLog(ConsoleLogMsg),
    FileComplete(FileCompleteMsg),
    ChunkedBatch(ChunkedBatchMsg),
    Error(ErrorMsg),
}

/// Errors returned by [`HistorySource::read`].
///
/// Go's interface method returns the open `error` type and callers only ever
/// test `errors.Is(err, io.EOF)`; this enum keeps that contract via
/// [`HistorySourceError::is_eof`].
#[derive(Debug, thiserror::Error)]
pub enum HistorySourceError {
    /// Go: bare `io.EOF` — the history source has been completely read.
    #[error("EOF")]
    Eof,

    /// A live-store error passed through (Go returns it unwrapped).
    #[error(transparent)]
    LiveStore(#[from] LiveStoreError),

    /// Any other source error (Go's open `error` interface; used by the
    /// parquet history source in leet-remote).
    #[error(transparent)]
    Other(Box<dyn std::error::Error + Send + Sync>),
}

impl HistorySourceError {
    /// Go: `errors.Is(err, io.EOF)`.
    pub fn is_eof(&self) -> bool {
        match self {
            Self::Eof => true,
            Self::LiveStore(err) => err.is_eof(),
            Self::Other(_) => false,
        }
    }
}

/// HistorySource is an interface for reading W&B run history data.
///
/// Implementations:
///   - LevelDBHistorySource: Reads from a LevelDB-style .wandb transaction log
///   - ParquetHistorySource: Reads from a run's exported parquet history files.
///     The files are downloaded from the W&B backend.
///
/// The Read method returns a ChunkedBatchMsg containing processed records,
/// and may return io.EOF when the stream is complete.
pub trait HistorySource {
    /// Read reads events from the history source,
    /// up to a given number of records or a given time period,
    /// whichever is reached first.
    ///
    /// Returns a ChunkedBatchMsg with processed records and metadata.
    /// If the history source has been completely read, it returns io.EOF error.
    // PARITY: Go returns `(tea.Msg, error)` where BOTH may be set at once —
    // the final ChunkedBatchMsg is returned alongside io.EOF — so the Go
    // tuple shape is kept instead of a Result.
    fn read(
        &mut self,
        chunk_size: usize,
        max_time_per_chunk: Duration,
    ) -> (Option<SourceMsg>, Option<HistorySourceError>);

    /// Close closes the history source that is being read from.
    fn close(&mut self);
}

/// ReadRecords returns a command to read te given number of records for the given time period.
// PARITY: Go returns a tea.Cmd closure; this is the closure body — leet-tui's
// effect runner invokes it off-thread and feeds the Option<SourceMsg> (nil
// tea.Msg ↔ None) into the event channel (docs/CONCURRENCY.md §2.7).
pub fn read_records(
    source: &mut dyn HistorySource,
    chunk_size: usize,
    max_time_per_chunk: Duration,
) -> Option<SourceMsg> {
    let mut max_time_per_chunk = max_time_per_chunk;
    if test_mode::enabled() {
        // Deterministic chunk boundaries: bound by record count only.
        max_time_per_chunk = Duration::from_secs(24 * 60 * 60);
    }
    let (msgs, err) = source.read(chunk_size, max_time_per_chunk);
    if let Some(err) = err
        && !err.is_eof()
    {
        return Some(SourceMsg::Error(ErrorMsg { err: Box::new(err) }));
    }
    msgs
}

/// Go: `concatenateHistory` — merges a batch of HistoryMsgs into one.
///
/// Go-unexported; pub here for the parquet history source in leet-remote
/// (same convention as `media::resolve_media_path`).
pub fn concatenate_history(messages: &[HistoryMsg], run_path: &str) -> HistoryMsg {
    let mut h = HistoryMsg {
        run_path: run_path.to_string(),
        metrics: HashMap::new(),
        media: HashMap::new(),
    };
    for msg in messages {
        // PARITY: Go iterates these maps unordered; the appends are keyed
        // per metric/media key, so the result is order-independent.
        for (metric_name, data) in &msg.metrics {
            let existing = h.metrics.entry(metric_name.clone()).or_default();
            existing.x.extend_from_slice(&data.x);
            existing.y.extend_from_slice(&data.y);
        }
        for (media_key, points) in &msg.media {
            h.media
                .entry(media_key.clone())
                .or_default()
                .extend_from_slice(points);
        }
    }

    // PARITY: Go sets empty Metrics/Media maps to nil here; nil and empty
    // maps are indistinguishable to every reader (see HistoryMsg), so the
    // maps simply stay empty.

    h
}

/// Go: `concatenateSummary` — merges a batch of SummaryMsgs into one.
///
/// Go-unexported; pub for leet-remote (see [`concatenate_history`]).
pub fn concatenate_summary(messages: &[SummaryMsg], run_path: &str) -> SummaryMsg {
    let mut s = SummaryMsg {
        run_path: run_path.to_string(),
        summary: Vec::new(),
    };
    for msg in messages {
        s.summary.extend(msg.summary.iter().cloned());
    }
    s
}

// PARITY: DEFERRED TESTS — of `core/internal/leet/liveread_test.go`'s six
// cases (see the note in leet-wire/src/live_store.rs), the HistorySource-layer
// ones land here and in leveldb_history_source:
//   - TestReadRecords_PassesThroughArguments (below)
//   - TestParseHistory_UsesHistoryStepFallback (leveldb_history_source)
// The remaining four exercise Run.ReadLiveBatchCmd / Workspace.ReadAvailableCmd
// (runhandlers.go / workspacehandlers.go) and MUST be transliterated by the
// leet-tui units porting those modules (docs/PARITY.md §5.1).
#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;

    use super::*;

    struct StubHistorySource {
        msg: Option<SourceMsg>,
        err: Option<HistorySourceError>,

        chunk_size: usize,
        max_time: Duration,
    }

    impl HistorySource for StubHistorySource {
        // PARITY: the Go stub returns the same (msg, err) pair on every call;
        // SourceMsg is not Clone (ErrorMsg boxes a dyn Error), so the stub
        // hands its payload out once — the tests read only once.
        fn read(
            &mut self,
            chunk_size: usize,
            max_time: Duration,
        ) -> (Option<SourceMsg>, Option<HistorySourceError>) {
            self.chunk_size = chunk_size;
            self.max_time = max_time;
            (self.msg.take(), self.err.take())
        }

        fn close(&mut self) {}
    }

    // Go: TestReadRecords_PassesThroughArguments (liveread_test.go).
    #[test]
    fn read_records_passes_through_arguments() {
        let mut src = StubHistorySource {
            msg: Some(SourceMsg::ChunkedBatch(ChunkedBatchMsg::default())),
            err: None,
            chunk_size: 0,
            max_time: Duration::ZERO,
        };

        let _ = read_records(&mut src, 17, Duration::from_millis(23));

        assert_eq!(src.chunk_size, 17);
        assert_eq!(src.max_time, Duration::from_millis(23));
    }

    // Port-added coverage (no Go counterpart): read_records swallows EOF and
    // passes the batch through; a non-EOF error becomes an ErrorMsg.
    #[test]
    fn read_records_eof_and_error_paths() {
        let mut src = StubHistorySource {
            msg: Some(SourceMsg::ChunkedBatch(ChunkedBatchMsg::default())),
            err: Some(HistorySourceError::Eof),
            chunk_size: 0,
            max_time: Duration::ZERO,
        };
        let msg = read_records(&mut src, 1, Duration::from_millis(1));
        assert!(matches!(msg, Some(SourceMsg::ChunkedBatch(_))));

        let mut src = StubHistorySource {
            msg: Some(SourceMsg::ChunkedBatch(ChunkedBatchMsg::default())),
            err: Some(HistorySourceError::Other("boom".into())),
            chunk_size: 0,
            max_time: Duration::ZERO,
        };
        let msg = read_records(&mut src, 1, Duration::from_millis(1));
        let Some(SourceMsg::Error(err_msg)) = msg else {
            panic!("expected ErrorMsg");
        };
        assert_eq!(err_msg.err.to_string(), "boom");
    }

    // Port-added coverage (no Go counterpart): concatenateHistory merges
    // per-key across messages; concatenateSummary appends in order.
    #[test]
    fn concatenate_history_and_summary_merge() {
        let msgs = [
            HistoryMsg {
                run_path: "a".to_string(),
                metrics: HashMap::from([(
                    "loss".to_string(),
                    MetricData {
                        x: vec![1.0],
                        y: vec![0.5],
                    },
                )]),
                media: HashMap::from([(
                    "img".to_string(),
                    vec![MediaPoint {
                        x: 1.0,
                        ..Default::default()
                    }],
                )]),
            },
            HistoryMsg {
                run_path: "b".to_string(),
                metrics: HashMap::from([
                    (
                        "loss".to_string(),
                        MetricData {
                            x: vec![2.0],
                            y: vec![0.25],
                        },
                    ),
                    (
                        "acc".to_string(),
                        MetricData {
                            x: vec![2.0],
                            y: vec![0.9],
                        },
                    ),
                ]),
                media: HashMap::new(),
            },
        ];

        let h = concatenate_history(&msgs, "run/path.wandb");
        assert_eq!(h.run_path, "run/path.wandb");
        assert_eq!(h.metrics["loss"].x, vec![1.0, 2.0]);
        assert_eq!(h.metrics["loss"].y, vec![0.5, 0.25]);
        assert_eq!(h.metrics["acc"].y, vec![0.9]);
        assert_eq!(h.media["img"].len(), 1);

        let empty = concatenate_history(&[], "run/path.wandb");
        assert!(empty.metrics.is_empty());
        assert!(empty.media.is_empty());

        let s = concatenate_summary(
            &[
                SummaryMsg {
                    run_path: "a".to_string(),
                    summary: vec![SummaryRecord::default()],
                },
                SummaryMsg {
                    run_path: "b".to_string(),
                    summary: vec![SummaryRecord::default(), SummaryRecord::default()],
                },
            ],
            "run/path.wandb",
        );
        assert_eq!(s.run_path, "run/path.wandb");
        assert_eq!(s.summary.len(), 3);
    }
}
