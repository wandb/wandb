//! Port of `core/internal/leet/livestore.go` — live reading of a .wandb file
//! that may be actively written to by another process.
//!
//! # PARITY notes (Go → Rust API mapping)
//!
//! - Go guards `Read`/`Close` with `LiveStore.mu sync.Mutex` because reads
//!   happen on `tea.Cmd` goroutines that could overlap. Per
//!   `docs/CONCURRENCY.md` (S5) the Rust port gives the store to a single
//!   reader thread, so the mutex dies; `&mut self` enforces exclusive access.
//! - Go's `NewLiveStore` takes an `*observability.CoreLogger`; the Rust port
//!   logs via `tracing` at the same call sites, so there is no logger
//!   parameter (workspace convention, see [`crate::transaction_log`]).

use std::fs::File;
use std::path::Path;

use leet_proto::wandb_internal;

use crate::transaction_log::{self, TransactionLogError};

/// Errors produced by [`LiveStore`].
///
/// Each variant's `Display` matches the corresponding Go error string.
#[derive(Debug, thiserror::Error)]
pub enum LiveStoreError {
    /// Go: `fmt.Errorf("livestore: failed opening reader: %w", err)`.
    #[error("livestore: failed opening reader: {0}")]
    OpenReader(#[source] TransactionLogError),

    /// Go: `fmt.Errorf("livestore: reader is closed")`.
    #[error("livestore: reader is closed")]
    ReaderClosed,

    /// Go: bare `io.EOF`, after LiveStore's unexpected-EOF mapping.
    ///
    /// PARITY: when the read error wraps `io.ErrUnexpectedEOF`, Go replaces
    /// the WHOLE wrapped error with plain `io.EOF`, discarding the
    /// transaction-log context; this variant is that bare `io.EOF`.
    #[error("EOF")]
    Eof,

    /// A transaction-log error passed through (Go joins it unwrapped).
    #[error(transparent)]
    TransactionLog(#[from] TransactionLogError),

    /// Go: `errors.Join(err, resetErr)` from [`LiveStore::read`]. `Display`
    /// joins the messages with a newline, like Go's `joinError`; nil errors
    /// are filtered out before joining.
    #[error("{}", join_errors(.0))]
    Joined(Vec<LiveStoreError>),
}

/// Go: `errors.Join` joins the error messages with a newline.
fn join_errors(errs: &[LiveStoreError]) -> String {
    errs.iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>()
        .join("\n")
}

impl LiveStoreError {
    /// Go: `errors.Is(err, io.EOF)`.
    ///
    /// True if the error indicates end of data, which for live reading may be
    /// resolved by waiting for more data and reading again.
    ///
    /// PARITY: mirrors Go's `errors.Is` traversal — `errors.Join` errors
    /// match if any joined error matches, and `%w`-wrapped errors unwrap.
    pub fn is_eof(&self) -> bool {
        match self {
            Self::Eof => true,
            Self::OpenReader(err) | Self::TransactionLog(err) => err.is_eof(),
            Self::Joined(errs) => errs.iter().any(LiveStoreError::is_eof),
            Self::ReaderClosed => false,
        }
    }
}

/// LiveStore is the persistent store for a stream that may be actively
/// written to by another process.
#[derive(Debug)]
pub struct LiveStore {
    /// The transaction-log reader; `None` when closed. (Go: nil when closed.)
    reader: Option<transaction_log::Reader<File>>,
}

impl LiveStore {
    /// Go: `NewLiveStore`.
    pub fn new(filename: impl AsRef<Path>) -> Result<LiveStore, LiveStoreError> {
        let reader = transaction_log::open_reader(filename).map_err(LiveStoreError::OpenReader)?;

        Ok(LiveStore {
            reader: Some(reader),
        })
    }

    /// Reads the next record from the database.
    pub fn read(&mut self) -> Result<wandb_internal::Record, LiveStoreError> {
        let Some(reader) = self.reader.as_mut() else {
            return Err(LiveStoreError::ReaderClosed);
        };

        match reader.read() {
            Ok(record) => Ok(record),
            Err(err) => {
                // We treat unexpected EOFs the same as regular EOFs for live
                // reading.
                //
                // PARITY: Go replaces the whole wrapped error with bare
                // io.EOF here (see LiveStoreError::Eof).
                let err = if err.is_unexpected_eof() {
                    LiveStoreError::Eof
                } else {
                    LiveStoreError::TransactionLog(err)
                };

                // Go: `return nil, errors.Join(err, resetErr)` — errors.Join
                // filters nil, so the joined list has one or two elements.
                let mut errs = vec![err];
                if let Err(reset_err) = reader.reset_last_read() {
                    errs.push(LiveStoreError::TransactionLog(reset_err));
                }
                Err(LiveStoreError::Joined(errs))
            }
        }
    }

    /// Close closes the database.
    pub fn close(&mut self) {
        let Some(mut reader) = self.reader.take() else {
            return;
        };

        reader.close();
    }
}

// PARITY: DEFERRED TESTS — `core/internal/leet/liveread_test.go` exercises the
// HistorySource layer above LiveStore, none of which lives in `leet-wire`:
// `ReadRecords` (historysource.go), `Run.ReadLiveBatchCmd` (runhandlers.go),
// `Workspace.ReadAvailableCmd` (workspacehandlers.go) and `ParseHistory`
// (leveldbhistorysource.go). The units porting those modules MUST
// transliterate all of its cases; this debt is tracked in
// `docs/PARITY.md` §5.1 (do not flip the liveread_test.go row to `done`
// until all six land):
//   - TestReadRecords_PassesThroughArguments (history_source)
//   - TestRun_ReadLiveBatchCmd_WrapsChunkedBatchAndUsesLiveLimits (leet-tui run)
//   - TestRun_ReadLiveBatchCmd_DropsEmptyChunk (leet-tui run)
//   - TestWorkspace_ReadAvailableCmd_WrapsChunkedBatch (leet-tui workspace)
//   - TestWorkspace_ReadAvailableCmd_DropsEmptyChunk (leet-tui workspace)
//   - TestParseHistory_UsesHistoryStepFallback (leveldb_history_source)
