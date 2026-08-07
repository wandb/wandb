//! Port of `core/internal/transactionlog` — reading and writing .wandb files.
//!
//! # PARITY notes (Go → Rust API mapping)
//!
//! - Go's reader constructors take an `*observability.CoreLogger`; the Rust
//!   port logs via `tracing` at the same call sites, so there is no logger
//!   parameter (workspace convention, see `leet-data::config`).
//! - Go's `SeekRecord` would fail at runtime with `ErrNotAnIOSeeker` for a
//!   non-seekable source; here seeking requires `R: Seek` at compile time
//!   (same convention as [`crate::record`]).
//! - Go wraps some errors with `%w` (participating in `errors.Is`) and
//!   others with `%v` (opaque). [`TransactionLogError::record_error`] and
//!   [`TransactionLogError::io_error`] mirror that reachability exactly: only
//!   the `%w`-wrapped errors are exposed.

use std::fs::{File, OpenOptions};
use std::io::{self, Read, Seek};
use std::path::Path;

use leet_proto::wandb_internal;
use prost::Message as _;

use crate::crc::CrcAlgo;
use crate::record::{self, RecordError};

/// wandbStoreVersion is written into .wandb file headers.
///
/// Incrementing this prevents older clients from attempting to read .wandb
/// files in a new format.
const WANDB_STORE_VERSION: u8 = 0;

/// Errors produced by [`Reader`] and [`Writer`].
///
/// Each variant's `Display` matches the corresponding Go error string.
#[derive(Debug, thiserror::Error)]
pub enum TransactionLogError {
    /// Go: `fmt.Errorf("transactionlog: error opening file %w", err)`.
    ///
    /// PARITY: Go's message has no separator before the wrapped error; the
    /// missing colon is intentional.
    #[error("transactionlog: error opening file {0}")]
    OpenFile(#[source] io::Error),

    /// Go: `fmt.Errorf("transactionlog: error creating file: %w", err)`.
    #[error("transactionlog: error creating file: {0}")]
    CreateFile(#[source] io::Error),

    /// Go: `fmt.Errorf("transactionlog: error writing header: %v", err)`.
    #[error("transactionlog: error writing header: {0}")]
    WriteHeader(RecordError),

    /// Go: `errors.New("transactionlog: reader is closed")`.
    #[error("transactionlog: reader is closed")]
    ReaderClosed,

    /// Go: `fmt.Errorf("transactionlog: bad header: %w", err)`.
    #[error("transactionlog: bad header: {0}")]
    BadHeader(#[source] RecordError),

    /// Go: `fmt.Errorf("transactionlog: error getting next record: %w", err)`.
    #[error("transactionlog: error getting next record: {0}")]
    NextRecord(#[source] RecordError),

    /// Go: `fmt.Errorf("transactionlog: error reading: %w", err)`.
    #[error("transactionlog: error reading: {0}")]
    ReadRecord(#[source] RecordError),

    /// Go: `fmt.Errorf("transactionlog: error unmarshaling: %v", err)`.
    #[error("transactionlog: error unmarshaling: {0}")]
    Unmarshal(prost::DecodeError),

    /// Go: `errors.New("transactionlog: writer is closed")`.
    #[error("transactionlog: writer is closed")]
    WriterClosed,

    /// Go: `errors.New("transactionlog: writer already closed")`.
    #[error("transactionlog: writer already closed")]
    WriterAlreadyClosed,

    /// Go: `fmt.Errorf("transactionlog: error marshaling: %v", err)`.
    ///
    /// PARITY: unreachable through this API — prost encoding into a `Vec`
    /// cannot fail. The variant is kept so the Go error class exists.
    #[error("transactionlog: error marshaling: {0}")]
    Marshal(prost::EncodeError),

    /// Go: `fmt.Errorf("transactionlog: error starting next record: %v", err)`.
    #[error("transactionlog: error starting next record: {0}")]
    StartNextRecord(RecordError),

    /// Go: `fmt.Errorf("transactionlog: error writing: %v", err)`.
    #[error("transactionlog: error writing: {0}")]
    WriteRecord(RecordError),

    /// Go: `fmt.Errorf("transactionlog: error closing writer: %v", err)`.
    #[error("transactionlog: error closing writer: {0}")]
    CloseWriter(RecordError),

    /// Go: `fmt.Errorf("transactionlog: error closing file: %v", err)`.
    ///
    /// PARITY: Go surfaces `f.Close()` errors ("An error could indicate that
    /// not all data was written"); `std::fs::File` swallows close errors on
    /// drop, so the Rust port calls `File::sync_all` before dropping, which
    /// surfaces a superset of the failures `close(2)` reports (e.g. NFS,
    /// quota).
    #[error("transactionlog: error closing file: {0}")]
    CloseFile(io::Error),

    /// Go: `errors.Join(errs...)` from [`Writer::close`]. `Display` joins the
    /// messages with a newline, like Go's `joinError`.
    #[error("{}", join_errors(.0))]
    Joined(Vec<TransactionLogError>),

    /// A record-layer error passed through unwrapped (Go returns `leveldb`
    /// errors directly from `SeekRecord`, `Flush` and `LastRecordOffset`).
    #[error(transparent)]
    Record(#[from] RecordError),
}

/// Go: `errors.Join` joins the error messages with a newline.
fn join_errors(errs: &[TransactionLogError]) -> String {
    errs.iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>()
        .join("\n")
}

impl TransactionLogError {
    /// Returns the record-layer error this error wraps, if any.
    ///
    /// PARITY: mirrors Go's `errors.Is` reachability — only the errors that
    /// Go wraps with `%w` ([`Self::BadHeader`], [`Self::NextRecord`],
    /// [`Self::ReadRecord`]) or returns unwrapped ([`Self::Record`]) are
    /// exposed; the `%v`-formatted errors deliberately do not unwrap.
    pub fn record_error(&self) -> Option<&RecordError> {
        match self {
            Self::BadHeader(err)
            | Self::NextRecord(err)
            | Self::ReadRecord(err)
            | Self::Record(err) => Some(err),
            _ => None,
        }
    }

    /// Returns the OS-level error this error wraps, if any.
    ///
    /// Go: `errors.Is(err, os.ErrNotExist)` / `errors.Is(err, os.ErrExist)`
    /// reach these through `%w`.
    pub fn io_error(&self) -> Option<&io::Error> {
        match self {
            Self::OpenFile(err) | Self::CreateFile(err) => Some(err),
            _ => None,
        }
    }

    /// Go: `errors.Is(err, io.EOF)`.
    ///
    /// With [`Self::is_unexpected_eof`], indicates that the error may be
    /// resolved by waiting for more data.
    pub fn is_eof(&self) -> bool {
        matches!(self.record_error(), Some(RecordError::Eof))
    }

    /// Go: `errors.Is(err, io.ErrUnexpectedEOF)`.
    ///
    /// With [`Self::is_eof`], indicates that the error may be resolved by
    /// waiting for more data.
    pub fn is_unexpected_eof(&self) -> bool {
        matches!(self.record_error(), Some(RecordError::UnexpectedEof))
    }
}

/// Reader reads from a .wandb file.
///
/// Not safe for use in multiple goroutines. (Rust: `&mut self` enforces this.)
pub struct Reader<R> {
    /// The record-layer reader; `None` when closed. (Go: nil when closed.)
    ///
    /// PARITY: Go also keeps the `io.ReadCloser` source to close it in
    /// `Close`; the Rust record reader owns the source, which is dropped
    /// (closing any file) when this is set to `None`.
    reader: Option<record::Reader<R>>,

    /// buf is the buffer reused as the Record buffer between Read()
    /// operations.
    ///
    /// This assumes that a large record is likely to be followed by another
    /// large record, so reusing a single large allocation reduces GC pressure
    /// and is probably not wasteful.
    ///
    /// PARITY: Go keeps this in a per-Reader `sync.Pool` holding at most one
    /// `bytes.Buffer`, so the allocation can be GC'ed when reading pauses for
    /// some time; Rust has no GC, so a plain reusable buffer serves the same
    /// purpose (the capacity persists for the Reader's lifetime).
    buf: Vec<u8>,

    /// last_read_offset is the offset the last Read started at, used for
    /// retrying that Read from the same position.
    last_read_offset: i64,

    /// needs_to_verify_header is true if the reader is positioned at start and
    /// the W&B header is yet to be successfully verified.
    needs_to_verify_header: bool,
}

impl<R> std::fmt::Debug for Reader<R> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Reader")
            .field("closed", &self.reader.is_none())
            .field("last_read_offset", &self.last_read_offset)
            .field("needs_to_verify_header", &self.needs_to_verify_header)
            .finish_non_exhaustive()
    }
}

/// OpenReader opens a .wandb file for reading.
///
/// Wraps errors from the `File::open()` call so that they can be checked
/// with [`TransactionLogError::io_error`] (Go: `errors.Is()`).
pub fn open_reader(path: impl AsRef<Path>) -> Result<Reader<File>, TransactionLogError> {
    let f = File::open(path).map_err(TransactionLogError::OpenFile)?;

    // PARITY: Go closes the file if NewReader fails; new_reader cannot fail,
    // and the file would be dropped (closed) on the error path anyway.
    new_reader(f)
}

/// NewReader starts reading a .wandb file from the given source.
///
/// On success, takes ownership of the source (it should not be used except
/// through the returned Reader).
///
/// PARITY: Go's `NewReader` returns an error but currently never fails; the
/// `Result` is kept for signature parity.
pub fn new_reader<R: Read>(source: R) -> Result<Reader<R>, TransactionLogError> {
    let reader = record::Reader::new_ext(source, CrcAlgo::Ieee);

    Ok(Reader {
        reader: Some(reader),
        buf: Vec::new(),
        last_read_offset: 0,
        needs_to_verify_header: true,
    })
}

impl<R: Read> Reader<R> {
    /// Read returns the next record from the transaction log.
    ///
    /// Returns an error on failure.
    /// On EOF, the error wraps EOF ([`TransactionLogError::is_eof`]).
    ///
    /// Errors are not fatal, and calling `read` again will attempt to skip
    /// corrupt data. [`Reader::reset_last_read`] can be used to attempt to
    /// read the same position in the transaction log again. The error wraps
    /// EOF or UnexpectedEof if it may be resolved by waiting for more data.
    pub fn read(&mut self) -> Result<wandb_internal::Record, TransactionLogError> {
        self.read_into_buf()?;

        let msg = wandb_internal::Record::decode(self.buf.as_slice())
            .map_err(TransactionLogError::Unmarshal)?;

        Ok(msg)
    }

    /// Reads the next record and returns its raw serialized payload bytes,
    /// without decoding them.
    ///
    /// Not part of the Go API (harness-only): used by the `wiredump`
    /// differential tool, which hashes the exact payload bytes as read from
    /// the log. Error behavior is identical to [`Reader::read`] except that
    /// unmarshal errors cannot occur.
    pub fn read_raw(&mut self) -> Result<Vec<u8>, TransactionLogError> {
        self.read_into_buf()?;
        Ok(self.buf.clone())
    }

    /// The shared body of [`Reader::read`] and [`Reader::read_raw`]: reads the
    /// next record's payload into `self.buf`.
    fn read_into_buf(&mut self) -> Result<(), TransactionLogError> {
        if self.reader.is_none() {
            return Err(TransactionLogError::ReaderClosed);
        }

        let result = self.read_inner();

        // Always recover after errors, skipping corrupt data.
        // No-op if there is no error.
        // (Go: `defer r.reader.Recover()`. Go runs the deferred Recover after
        // proto unmarshaling, but unmarshaling does not touch reader state, so
        // decoding after this point is equivalent.)
        self.reader
            .as_mut()
            .expect("transactionlog: reader is closed")
            .recover();

        result
    }

    /// The body of [`Reader::read_into_buf`] between the closed-check and the
    /// deferred `Recover()`. The record reader is guaranteed to be present.
    fn read_inner(&mut self) -> Result<(), TransactionLogError> {
        self.last_read_offset = self
            .reader
            .as_ref()
            .expect("transactionlog: reader is closed")
            .next_offset();

        // Verify the W&B header before the first read.
        self.verify_wb_header_before_first_read()?;

        // Borrow the record reader and the buffer disjointly.
        let reader = self
            .reader
            .as_mut()
            .expect("transactionlog: reader is closed");
        let buf = &mut self.buf;

        let record_reader = reader.next().map_err(TransactionLogError::NextRecord)?;

        // Go: `io.Copy(buf, recordReader)` into the pooled buffer, which is
        // reset and returned to the pool after use.
        buf.clear();
        let mut chunk = [0u8; 512];
        loop {
            match record_reader.read(reader, &mut chunk) {
                Ok(n) => buf.extend_from_slice(&chunk[..n]),
                Err(RecordError::Eof) => break,
                Err(err) => return Err(TransactionLogError::ReadRecord(err)),
            }
        }

        Ok(())
    }

    /// verifyWBHeaderBeforeFirstRead verifies the W&B header if it hasn't yet
    /// been verified.
    fn verify_wb_header_before_first_read(&mut self) -> Result<(), TransactionLogError> {
        if !self.needs_to_verify_header {
            return Ok(());
        }

        self.reader
            .as_mut()
            .expect("transactionlog: reader is closed")
            .verify_wandb_header(WANDB_STORE_VERSION)
            .map_err(TransactionLogError::BadHeader)?;

        self.needs_to_verify_header = false;
        Ok(())
    }

    /// Close closes the file.
    ///
    /// The reader may not be used after.
    ///
    /// PARITY: Go logs a warning if closing the source fails ("since we only
    /// use the file for reading, we do not care about errors when closing");
    /// Rust drops the source here, and `std::fs::File` swallows close errors
    /// on drop, so there is nothing to log.
    pub fn close(&mut self) {
        self.reader = None;
    }
}

impl<R: Read + Seek> Reader<R> {
    /// SeekRecord seeks the underlying file to a specific offset.
    ///
    /// The offset should have come from a writer's
    /// [`Writer::last_record_offset`].
    ///
    /// PARITY: Go nil-dereferences (panics) if called after `Close`; the
    /// `expect` matches.
    pub fn seek_record(&mut self, offset: i64) -> Result<(), TransactionLogError> {
        self.needs_to_verify_header = false; // May not be at the start anymore.
        self.reader
            .as_mut()
            .expect("transactionlog: reader is closed")
            .seek_record(offset)?;
        Ok(())
    }

    /// ResetLastRead returns to the previous Read position to allow retrying
    /// the same read after an error.
    pub fn reset_last_read(&mut self) -> Result<(), TransactionLogError> {
        tracing::debug!(
            offset = self.last_read_offset,
            "transactionlog: resetting to offset"
        );
        self.seek_record(self.last_read_offset)
    }
}

/// Writer creates a .wandb file.
///
/// Not safe for use in multiple goroutines. (Rust: `&mut self` enforces this.)
pub struct Writer {
    /// The record-layer writer; `None` when closed. (Go: nil when closed.)
    ///
    /// PARITY: Go also keeps the `*os.File` to close it separately in
    /// `Close`; the Rust record writer owns the file, which is closed when
    /// dropped.
    writer: Option<record::Writer<File>>,
}

impl std::fmt::Debug for Writer {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Writer")
            .field("closed", &self.writer.is_none())
            .finish_non_exhaustive()
    }
}

/// OpenWriter opens a .wandb file for writing.
///
/// The file must not already exist. It is created with permissions 0o666
/// (meaning read and write permissions for user, group and others).
///
/// The file header is output immediately, so that [`open_reader`] can open it
/// before any records are written.
///
/// The parent directory must exist.
///
/// Wraps errors from the file-creation call so that they can be checked
/// with [`TransactionLogError::io_error`] (Go: `errors.Is()`).
pub fn open_writer(path: impl AsRef<Path>) -> Result<Writer, TransactionLogError> {
    // O_EXCL (create_new) returns an error if the file already exists.
    //
    // Note that os.Create() silently truncates an existing file,
    // which is very bad if it happens to be an actual transaction log.
    // Could happen due to a race between two wandb scripts!
    //
    // PARITY: Go passes permissions 0o666 explicitly; Rust's OpenOptions
    // default mode is 0o666 on Unix, so no explicit mode is needed.
    let f = OpenOptions::new()
        .create_new(true) // O_CREATE|O_EXCL
        .write(true) // O_WRONLY
        .open(path)
        .map_err(TransactionLogError::CreateFile)?;

    // PARITY: Go's NewWriterExt detects that *os.File is an io.Seeker and
    // uses its position as the base offset; new_ext_seekable matches.
    let mut writer = record::Writer::new_ext_seekable(f, CrcAlgo::Ieee, WANDB_STORE_VERSION);

    // Flush immediately to write the file's header.
    if let Err(err) = writer.flush() {
        // Go: `_ = f.Close()` — dropping the writer closes the file.
        return Err(TransactionLogError::WriteHeader(err));
    }

    Ok(Writer {
        writer: Some(writer),
    })
}

impl Writer {
    /// Write writes the next record into the transaction log.
    pub fn write(&mut self, msg: &wandb_internal::Record) -> Result<(), TransactionLogError> {
        let Some(writer) = self.writer.as_mut() else {
            return Err(TransactionLogError::WriterClosed);
        };

        // PARITY: Go's proto.Marshal can fail ("transactionlog: error
        // marshaling: %v"); prost encoding into a Vec cannot, so that branch
        // has no Rust counterpart.
        let msg_bytes = msg.encode_to_vec();

        let record_writer = writer
            .next()
            .map_err(TransactionLogError::StartNextRecord)?;

        // NOTE: The io.Writer contract guarantees a non-nil error on a short write.
        record_writer
            .write(writer, &msg_bytes)
            .map_err(TransactionLogError::WriteRecord)?;

        Ok(())
    }

    /// Flush flushes the in-memory store to disk.
    ///
    /// PARITY: Go nil-dereferences (panics) if called after `Close`; the
    /// `expect` matches.
    pub fn flush(&mut self) -> Result<(), TransactionLogError> {
        self.writer
            .as_mut()
            .expect("transactionlog: writer is closed")
            .flush()?;
        Ok(())
    }

    /// LastRecordOffset returns the offset where the last record was written.
    ///
    /// PARITY: Go nil-dereferences (panics) if called after `Close`; the
    /// `expect` matches.
    pub fn last_record_offset(&self) -> Result<i64, TransactionLogError> {
        Ok(self
            .writer
            .as_ref()
            .expect("transactionlog: writer is closed")
            .last_record_offset()?)
    }

    /// Close closes the file.
    ///
    /// The writer may not be used after.
    /// An error could indicate that not all data was written.
    pub fn close(&mut self) -> Result<(), TransactionLogError> {
        let Some(mut writer) = self.writer.take() else {
            return Err(TransactionLogError::WriterAlreadyClosed);
        };

        let mut errs: Vec<TransactionLogError> = Vec::new();

        if let Err(err) = writer.close() {
            errs.push(TransactionLogError::CloseWriter(err));
        }

        // PARITY: Go closes the file explicitly and joins its error
        // ("transactionlog: error closing file: %v"); dropping the record
        // writer closes the file, but close errors on drop are unobservable,
        // so sync to disk first to surface (a superset of) the failures Go's
        // `f.Close()` would report (e.g. NFS, quota).
        if let Err(err) = writer.get_ref().sync_all() {
            errs.push(TransactionLogError::CloseFile(err));
        }
        drop(writer);

        // Go: `errors.Join(errs...)` — nil if empty.
        if errs.is_empty() {
            Ok(())
        } else {
            Err(TransactionLogError::Joined(errs))
        }
    }
}
