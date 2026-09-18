//! Port of `core/pkg/leveldb/record.go` (a fork of golang/leveldb's `record`
//! package, with W&B's customizations).
//!
//! Reads and writes sequences of records. Each record is a stream of bytes
//! that completes before the next record starts.
//!
//! When reading, call [`Reader::next`] to obtain a handle for the next record.
//! `next` returns an EOF error when there are no more records. It is valid to
//! call `next` without reading the current record to exhaustion.
//!
//! When writing, call [`Writer::next`] to obtain a handle for the next record.
//! Calling `next` finishes the current record. Call [`Writer::close`] to
//! finish the final record.
//!
//! Optionally, call [`Writer::flush`] to finish the current record and flush
//! the underlying writer without starting a new record. To start a new record
//! after flushing, call `next`.
//!
//! Neither Readers or Writers are safe to use concurrently.
//!
//! The wire format is that the stream is divided(*) into 32KiB blocks, and each
//! block contains a number of tightly packed chunks. Chunks cannot cross block
//! boundaries. The last block may be shorter than 32 KiB. Any unused bytes in a
//! block must be zero.
//!
//! (*) - W&B customizes this format such that the first 7 bytes of the stream
//! contain a custom header. These 7 bytes are subtracted from the initial block,
//! making it at most (32KiB - 7B) long.
//!
//! A record maps to one or more chunks. Each chunk has a 7 byte header (a 4
//! byte checksum, a 2 byte little-endian u16 length, and a 1 byte chunk type)
//! followed by a payload. The checksum is over the chunk type and the payload.
//!
//! There are four chunk types: whether the chunk is the full record, or the
//! first, middle or last chunk of a multi-chunk record. A multi-chunk record
//! has one first chunk, zero or more middle chunks, and one last chunk.
//!
//! The wire format allows for limited recovery in the face of data corruption:
//! on a format error (such as a checksum mismatch), the reader moves to the
//! next block and looks for the next full or first chunk.
//!
//! # PARITY notes (Go → Rust API mapping)
//!
//! - Go's `Next` returns `io.Reader`/`io.Writer` values holding a pointer back
//!   into the parent. Rust's borrow rules forbid two live `&mut` handles, so
//!   [`SingleReader`]/[`SingleWriter`] are sequence-number tokens whose
//!   `read`/`write` methods take the parent explicitly. Staleness is detected
//!   at runtime via the sequence number, exactly like Go.
//! - Go signals end-of-record/stream with `io.EOF` error values;
//!   [`RecordError::Eof`] mirrors that (instead of the Rust `Ok(0)` idiom) so
//!   error classes stay 1:1 with the Go spec.

// The C++ Level-DB code calls this the log, but it has been renamed to record
// to avoid clashing with the standard log package, and because it is generally
// useful outside of logging. The C++ code also uses the term "physical record"
// instead of "chunk", but "chunk" is shorter and less confusing.

use std::io::{self, Read, Seek, SeekFrom, Write};

use crate::crc::{CrcAlgo, crc_custom, crc_standard};

// These constants are part of the wire format and should not be changed.
const FULL_CHUNK_TYPE: u8 = 1;
const FIRST_CHUNK_TYPE: u8 = 2;
const MIDDLE_CHUNK_TYPE: u8 = 3;
const LAST_CHUNK_TYPE: u8 = 4;

pub(crate) const BLOCK_SIZE: usize = 32 * 1024;
const BLOCK_SIZE_MASK: i64 = BLOCK_SIZE as i64 - 1;
const HEADER_SIZE: usize = 7;

// W&B transaction log files begin with a 7-byte header (unrelated to the
// 7-byte LevelDB block header).
//
// The first block, if full, is 7 bytes short of 32 KiB.
const WANDB_HEADER_IDENT: &[u8; 4] = b":W&B";
const WANDB_HEADER_MAGIC: u16 = 0xBEE1;
pub(crate) const WANDB_HEADER_LENGTH: usize = 7; // ident(4) + magic(2) + version(1)

/// Errors produced by [`Reader`] and [`Writer`].
///
/// Mirrors the distinct error classes of the Go spec: `io.EOF`,
/// `io.ErrUnexpectedEOF`, the package's sentinel errors, and its
/// `errors.New`/`fmt.Errorf` strings (`Display` matches the Go messages).
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum RecordError {
    /// Go: `io.EOF`.
    #[error("EOF")]
    Eof,
    /// Go: `io.ErrUnexpectedEOF`.
    #[error("unexpected EOF")]
    UnexpectedEof,
    /// Go: `ErrNotAnIOSeeker`.
    ///
    /// PARITY: unreachable through this API — Go detects `io.Seeker` at
    /// runtime, while `seek_record` requires `R: Seek` at compile time. The
    /// variant is kept so the Go error class exists.
    #[error("leveldb/record: reader does not implement io.Seeker")]
    NotAnIoSeeker,
    /// Go: `ErrNoLastRecord`.
    #[error("leveldb/record: no last record exists")]
    NoLastRecord,
    /// Go: `errZeroChunk`, an internal-only error used to detect and skip
    /// zeroed blocks, which may occur for files created with mmap.
    #[error("leveldb/record: block appears to be zeroed")]
    ZeroChunk,
    /// Go: `errors.New("leveldb/record: next chunk is behind reader")`.
    #[error("leveldb/record: next chunk is behind reader")]
    ChunkBehindReader,
    /// Go: `fmt.Errorf("leveldb/record: chunk too long (%d)", length)`.
    #[error("leveldb/record: chunk too long ({0})")]
    ChunkTooLong(u16),
    /// Go: `errors.New("leveldb/record: invalid chunk (checksum mismatch)")`.
    #[error("leveldb/record: invalid chunk (checksum mismatch)")]
    ChecksumMismatch,
    /// Go: `errors.New("leveldb/record: stale reader")`.
    #[error("leveldb/record: stale reader")]
    StaleReader,
    /// Go: `errors.New("leveldb/record: stale writer")`.
    #[error("leveldb/record: stale writer")]
    StaleWriter,
    /// Go: `errors.New("leveldb/record: closed Writer")`.
    #[error("leveldb/record: closed Writer")]
    ClosedWriter,
    /// Go: `errors.New("leveldb/record: reader not in first block")`.
    #[error("leveldb/record: reader not in first block")]
    NotInFirstBlock,
    /// Go: `fmt.Errorf("leveldb/record: invalid W&B identifier: %X (%q)", ...)`.
    #[error(
        "leveldb/record: invalid W&B identifier: {} ({})",
        hex_upper(.0),
        go_quote(.0)
    )]
    InvalidWandbIdent([u8; 4]),
    /// Go: `fmt.Errorf("leveldb/record: invalid W&B magic: %X", magic)`.
    #[error("leveldb/record: invalid W&B magic: {0:X}")]
    InvalidWandbMagic(u16),
    /// Go: `fmt.Errorf("leveldb/record: expected W&B version %d but got %d", ...)`.
    #[error("leveldb/record: expected W&B version {expected} but got {got}")]
    WandbVersionMismatch {
        /// The version passed to `verify_wandb_header`.
        expected: u8,
        /// The version byte found in the file.
        got: u8,
    },
    /// An error from the underlying reader/writer (Go: any other error
    /// returned by `Read`/`Write`/`Seek`).
    ///
    /// Kind+message are stored (not `io::Error` itself) so the accumulated
    /// error can be returned again on subsequent calls, as Go does.
    #[error("{msg}")]
    Io {
        /// The [`io::ErrorKind`] of the underlying error.
        kind: io::ErrorKind,
        /// The rendered message of the underlying error.
        msg: String,
    },
}

impl From<io::Error> for RecordError {
    fn from(e: io::Error) -> Self {
        RecordError::Io {
            kind: e.kind(),
            msg: e.to_string(),
        }
    }
}

/// Go: `%X` of a byte slice (uppercase hex, two digits per byte).
fn hex_upper(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02X}")).collect()
}

/// Go: `%q` of a byte slice.
///
/// PARITY: approximates Go's `strconv.Quote` at the byte level (Go is
/// UTF-8-aware); identical for the printable-ASCII data this is used on.
fn go_quote(b: &[u8]) -> String {
    let mut s = String::from("\"");
    for &c in b {
        match c {
            b'"' => s.push_str("\\\""),
            b'\\' => s.push_str("\\\\"),
            b'\n' => s.push_str("\\n"),
            b'\r' => s.push_str("\\r"),
            b'\t' => s.push_str("\\t"),
            0x20..=0x7e => s.push(c as char),
            _ => s.push_str(&format!("\\x{c:02x}")),
        }
    }
    s.push('"');
    s
}

/// Maps a [`CrcAlgo`] to its checksum function, as Go's constructors do.
fn crc_fn(algo: CrcAlgo) -> fn(&[u8]) -> u32 {
    match algo {
        CrcAlgo::Ieee => crc_standard,
        CrcAlgo::Custom => crc_custom,
    }
}

/// Equivalent of Go's `io.ReadFull` as used by `readBlock`: reads until `buf`
/// is full or EOF. Returns the number of bytes read; underlying read errors
/// (other than interruption) are returned as-is.
fn read_full<R: Read>(r: &mut R, buf: &mut [u8]) -> Result<usize, RecordError> {
    let mut n = 0;
    while n < buf.len() {
        match r.read(&mut buf[n..]) {
            Ok(0) => break,
            Ok(m) => n += m,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
    Ok(n)
}

/// Reader reads records from an underlying [`Read`].
pub struct Reader<R> {
    /// r is the underlying reader.
    r: R,

    /// seq is the sequence number of the current record.
    seq: i64,

    /// block_offset is the start position of the current block in the reader.
    ///
    /// If the reader started at position zero in a file, then this is
    /// the file offset of the first byte of buf.
    block_offset: i64,

    /// buf[i..j] is the unread portion of the current chunk's payload.
    /// The low bound, i, excludes the chunk header.
    ///
    /// If j is zero, then i is zero and there is no current chunk.
    i: usize,
    j: usize,

    /// next_chunk_start is the offset of the next chunk from the start of the
    /// current block.
    ///
    /// It may be greater than or equal to n, in which case the next chunk is in
    /// a future block. It is normally equal to j except when seeking or at the
    /// end of a padded block.
    next_chunk_start: i64,

    /// n is the number of bytes of buf that are valid. Once reading has started,
    /// only the final block can have n < BLOCK_SIZE.
    n: usize,

    /// recovering is true when recovering from corruption.
    recovering: bool,

    /// last is whether the current chunk is the last chunk of the record.
    last: bool,

    /// err is any accumulated error.
    err: Option<RecordError>,

    /// buf is the buffer.
    buf: Box<[u8; BLOCK_SIZE]>,

    /// CRC function.
    crc: fn(&[u8]) -> u32,
}

impl<R: Read> Reader<R> {
    /// Returns a new reader.
    ///
    /// The given reader must start with the W&B header.
    ///
    /// Go: `NewReaderExt`.
    pub fn new_ext(r: R, algo: CrcAlgo) -> Self {
        Reader {
            r,
            seq: 0,
            block_offset: 0,
            i: 0,
            j: 0,
            next_chunk_start: WANDB_HEADER_LENGTH as i64,
            n: 0,
            recovering: false,
            last: false,
            err: None,
            buf: Box::new([0u8; BLOCK_SIZE]),
            crc: crc_fn(algo),
        }
    }

    /// Returns a new reader.
    ///
    /// The given reader must start with the W&B header.
    ///
    /// Go: `NewReader`.
    pub fn new(r: R) -> Self {
        Self::new_ext(r, CrcAlgo::Custom)
    }

    /// Returns a shared reference to the underlying reader.
    pub fn get_ref(&self) -> &R {
        &self.r
    }

    /// Returns a mutable reference to the underlying reader.
    pub fn get_mut(&mut self) -> &mut R {
        &mut self.r
    }

    /// nextChunk sets buf[i..j] to hold the next chunk's payload, reading the
    /// next block into the buffer if necessary.
    fn next_chunk(&mut self, want_first: bool) -> Result<(), RecordError> {
        loop {
            if self.next_chunk_start < 0 {
                return Err(RecordError::ChunkBehindReader);
            }

            if self.next_chunk_start + HEADER_SIZE as i64 <= self.n as i64 {
                match self.read_chunk_in_block(self.next_chunk_start as usize) {
                    Err(err) => {
                        if self.recovering || (want_first && matches!(err, RecordError::ZeroChunk))
                        {
                            self.err = Some(err); // recover() requires err to be set
                            self.recover();
                            continue;
                        }

                        return Err(err);
                    }
                    Ok(chunk_type) => {
                        if want_first
                            && chunk_type != FULL_CHUNK_TYPE
                            && chunk_type != FIRST_CHUNK_TYPE
                        {
                            continue;
                        }

                        return Ok(());
                    }
                }
            }

            // There must be no bytes after the final chunk.
            //
            // We can only partially detect this error: the final chunk is the
            // last chunk in the final block, and we can detect a final block
            // only if it is not the full size. If it's a full block, it could be
            // a (potentially padded) middle block.
            //
            // If j is zero, then there is no current chunk.
            // Otherwise, the end of the chunk must equal the end of the block.
            if self.is_short_block() && 0 < self.j && self.j != self.n {
                return Err(RecordError::UnexpectedEof);
            }

            // If the next chunk was expected to be in the current block,
            // that's an unexpected EOF: it means this block contains some
            // but not all of the next chunk's bytes.
            //
            // If this is the final block and the next chunk offset is after its
            // end, that's a normal EOF.
            if self.next_chunk_start < self.n as i64 {
                return Err(RecordError::UnexpectedEof);
            }

            // Read the next block.
            self.read_block()?;
        }
    }

    /// readChunkInBlock sets up the reader to read the chunk at the given
    /// offset in the current block.
    ///
    /// Returns the chunk type on success.
    /// Returns [`RecordError::ZeroChunk`] if the chunk's header is zero.
    fn read_chunk_in_block(&mut self, start: usize) -> Result<u8, RecordError> {
        let checksum = u32::from_le_bytes(self.buf[start..start + 4].try_into().unwrap());
        let length = u16::from_le_bytes(self.buf[start + 4..start + 6].try_into().unwrap());
        let chunk_type = self.buf[start + 6];

        if checksum == 0 && length == 0 && chunk_type == 0 {
            return Err(RecordError::ZeroChunk);
        }

        self.i = start + HEADER_SIZE;
        self.j = start + HEADER_SIZE + length as usize;
        self.next_chunk_start = start_of_chunk_after(self.j) as i64;

        if self.j > BLOCK_SIZE {
            return Err(RecordError::ChunkTooLong(length));
        }
        if self.j > self.n {
            return Err(RecordError::UnexpectedEof);
        }
        if checksum != (self.crc)(&self.buf[self.i - 1..self.j]) {
            return Err(RecordError::ChecksumMismatch);
        }

        self.last = chunk_type == FULL_CHUNK_TYPE || chunk_type == LAST_CHUNK_TYPE;
        self.recovering = false;
        Ok(chunk_type)
    }

    /// readBlock reads the next block into buf.
    ///
    /// Assumes that the current block consists of the bytes starting from
    /// block_offset and going up to block_offset + n.
    ///
    /// Returns EOF if the current block is not full, in which case it must be
    /// final.
    fn read_block(&mut self) -> Result<(), RecordError> {
        if self.is_short_block() {
            return Err(RecordError::Eof);
        }

        let prev_block_size = self.n;
        let next_block_offset = self.block_offset + prev_block_size as i64;
        let n = read_full(&mut self.r, &mut self.buf[..])?;

        // PARITY: Go's io.ReadFull returns io.EOF when n == 0 (state is left
        // untouched). It's OK if 0 < n < BLOCK_SIZE, in which case Go gets
        // ErrUnexpectedEOF and ignores it.
        if n == 0 {
            return Err(RecordError::Eof);
        }

        self.block_offset = next_block_offset;
        self.i = 0;
        self.j = 0;
        self.n = n;
        self.next_chunk_start -= prev_block_size as i64;
        Ok(())
    }

    /// isShortBlock returns true if there is a block in memory and it is
    /// shorter than the block size, in which case it must be a final block.
    fn is_short_block(&self) -> bool {
        0 < self.n && self.n < BLOCK_SIZE
    }

    /// VerifyWandbHeader checks for a W&B header with the correct version.
    ///
    /// The reader must be positioned at the start.
    ///
    /// The error is EOF if there's no data at all and UnexpectedEof if there's
    /// not enough data to hold a header.
    pub fn verify_wandb_header(&mut self, expected_version: u8) -> Result<(), RecordError> {
        if self.block_offset != 0 {
            return Err(RecordError::NotInFirstBlock);
        }

        if self.n == 0
            && let Err(e) = self.read_block()
        {
            self.err = Some(e.clone());
            return Err(e);
        }

        if self.n < WANDB_HEADER_LENGTH {
            return Err(RecordError::UnexpectedEof);
        }

        let version = self.buf[6];

        if &self.buf[0..4] != WANDB_HEADER_IDENT {
            let mut ident = [0u8; 4];
            ident.copy_from_slice(&self.buf[0..4]);
            return Err(RecordError::InvalidWandbIdent(ident));
        }

        let magic = self.buf[4] as u16 + ((self.buf[5] as u16) << 8);
        if magic != WANDB_HEADER_MAGIC {
            return Err(RecordError::InvalidWandbMagic(magic));
        }

        if version != expected_version {
            return Err(RecordError::WandbVersionMismatch {
                expected: expected_version,
                got: version,
            });
        }

        Ok(())
    }

    /// NextOffset returns the offset from which `next()` will start to read.
    ///
    /// This offset can be passed to `seek_record` to return to the same record
    /// in the underlying file. If the underlying reader is not seekable or did
    /// not start at position 0, then the offset is not usable.
    pub fn next_offset(&self) -> i64 {
        self.block_offset + self.next_chunk_start
    }

    /// Next returns a handle for the next record.
    ///
    /// The handle's offset within the file is [`Reader::next_offset`] taken
    /// before this call; it can be passed to `seek_record` to return to this
    /// record in the underlying file.
    ///
    /// The error is [`RecordError::Eof`] if there are no more records and
    /// [`RecordError::UnexpectedEof`] if there's less data than expected based
    /// on the first chunk's header. In general, `Eof` and `UnexpectedEof` are
    /// returned if and only if the error may be resolved by appending more
    /// data to the file and using `seek_record` to reread the block. Other
    /// errors indicate data corruption.
    ///
    /// The handle becomes stale after the next call to `next()` and should no
    /// longer be used.
    #[allow(clippy::should_implement_trait)] // Go: Reader.Next; not an Iterator.
    pub fn next(&mut self) -> Result<SingleReader, RecordError> {
        self.seq += 1;
        if let Some(err) = &self.err {
            return Err(err.clone());
        }

        if let Err(err) = self.next_chunk(true) {
            self.err = Some(err.clone());
            return Err(err);
        }

        Ok(SingleReader { seq: self.seq })
    }

    /// Recover clears any errors read so far, so that calling `next` will
    /// start reading from the next good 32KiB block. If there are no such
    /// blocks, `next` will return EOF. Recover also marks the current reader,
    /// the one most recently returned by `next`, as stale. If Recover is
    /// called without any prior error, then Recover is a no-op.
    pub fn recover(&mut self) {
        if self.err.is_none() {
            return;
        }
        self.recovering = true;
        self.err = None;
        // Discard the rest of the current block.
        self.i = 0;
        self.j = 0;
        self.last = false;
        self.next_chunk_start = self.n as i64;
        // Invalidate any outstanding SingleReader.
        self.seq += 1;
    }
}

impl<R: Read + Seek> Reader<R> {
    /// SeekRecord seeks in the underlying reader such that calling `next`
    /// returns the record whose first chunk header starts at the provided
    /// offset. Its behavior is undefined if the argument given is not such an
    /// offset, as the bytes at that offset may coincidentally appear to be a
    /// valid header.
    ///
    /// SeekRecord will fail and return an error if the Reader previously
    /// encountered an error, including EOF. Such errors can be cleared by
    /// calling `recover`. Calling `seek_record` after `recover` will make
    /// calling `next` return the record at the given offset, instead of the
    /// record at the next good 32KiB block as `recover` normally would.
    ///
    /// The only other errors possible are those returned by the underlying
    /// `seek()`. In particular, for files, `seek()` never returns EOF even if
    /// seeking past the end of a file. In this case, `next()` will return EOF.
    ///
    /// The offset is always relative to the start of the underlying reader, so
    /// negative values will result in an error.
    ///
    /// PARITY: Go returns `ErrNotAnIOSeeker` when the reader is not an
    /// `io.Seeker`; here that is a compile-time `R: Seek` bound instead.
    pub fn seek_record(&mut self, offset: i64) -> Result<(), RecordError> {
        self.seq += 1;
        if let Some(err) = &self.err {
            return Err(err.clone());
        }

        // Clear the state of the internal reader.
        self.i = 0;
        self.j = 0;
        self.n = 0;
        self.recovering = false;
        self.last = false;

        // Seek to an exact block offset.
        self.next_chunk_start = offset & BLOCK_SIZE_MASK;
        self.block_offset = offset & !BLOCK_SIZE_MASK;

        // PARITY: Go passes negative offsets through to Seek, which errors as
        // per io.Seeker. Rust's SeekFrom::Start is unsigned, so synthesize the
        // io error without calling seek.
        let res = if self.block_offset < 0 {
            Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "leveldb/record: seek to negative position",
            ))
        } else {
            self.r
                .seek(SeekFrom::Start(self.block_offset as u64))
                .map(|_| ())
        };

        match res {
            Ok(()) => Ok(()),
            Err(e) => {
                let err = RecordError::from(e);
                self.err = Some(err.clone());
                Err(err)
            }
        }
    }
}

/// startOfChunkAfter returns the starting offset of the next chunk after
/// the chunk ending at the given offset in a block.
///
/// This requires a special case for padded blocks: if another chunk wouldn't
/// fit into the same block, then the next chunk starts in the next block.
fn start_of_chunk_after(chunk_end: usize) -> usize {
    // Only full-size blocks can be padded because the only non-full block
    // is the final block, so this logic only depends on the BLOCK_SIZE
    // constant and not the current reader state.
    if chunk_end + HEADER_SIZE <= BLOCK_SIZE {
        chunk_end
    } else {
        BLOCK_SIZE
    }
}

/// Handle to the record most recently returned by [`Reader::next`].
///
/// Go: `singleReader`. See the module PARITY notes for why the parent is
/// passed to each call instead of being captured.
#[derive(Debug, Clone, Copy)]
pub struct SingleReader {
    seq: i64,
}

impl SingleReader {
    /// Go: `singleReader.Read`.
    ///
    /// Returns [`RecordError::Eof`] at the end of the record (Go returns
    /// `(0, io.EOF)`).
    pub fn read<R: Read>(&self, r: &mut Reader<R>, p: &mut [u8]) -> Result<usize, RecordError> {
        if r.seq != self.seq {
            return Err(RecordError::StaleReader);
        }
        if let Some(err) = &r.err {
            return Err(err.clone());
        }
        while r.i == r.j {
            if r.last {
                return Err(RecordError::Eof);
            }

            if let Err(err) = r.next_chunk(false) {
                // Map EOF to UnexpectedEof since we expected more chunks.
                let err = if matches!(err, RecordError::Eof) {
                    RecordError::UnexpectedEof
                } else {
                    err
                };
                r.err = Some(err.clone());
                return Err(err);
            }
        }
        let n = p.len().min(r.j - r.i);
        p[..n].copy_from_slice(&r.buf[r.i..r.i + n]);
        r.i += n;
        Ok(n)
    }

    /// Reads the record to exhaustion, like Go's `io.ReadAll(rec)`.
    ///
    /// [`RecordError::Eof`] terminates the read successfully; any other error
    /// is returned (partial data is discarded).
    pub fn read_all<R: Read>(&self, r: &mut Reader<R>) -> Result<Vec<u8>, RecordError> {
        let mut out = Vec::new();
        let mut chunk = [0u8; 512];
        loop {
            match self.read(r, &mut chunk) {
                Ok(n) => out.extend_from_slice(&chunk[..n]),
                Err(RecordError::Eof) => return Ok(out),
                Err(e) => return Err(e),
            }
        }
    }
}

/// Writer writes records to an underlying [`Write`].
pub struct Writer<W> {
    /// w is the underlying writer.
    w: W,
    /// seq is the sequence number of the current record.
    seq: i64,
    /// buf[i..j] is the bytes that will become the current chunk.
    /// The low bound, i, includes the chunk header.
    i: usize,
    j: usize,
    /// buf[..written] has already been written to w.
    /// written is zero unless flush has been called.
    written: usize,
    /// base_offset is the base offset in w at which writing started. If
    /// the writer is seekable, it's relative to the start of w, 0 otherwise.
    base_offset: i64,
    /// block_number is the zero based block number currently held in buf.
    block_number: i64,
    /// last_record_offset is the offset in w where the last record was
    /// written (including the chunk header). It is a relative offset to
    /// base_offset, thus the absolute offset of the last record is
    /// base_offset + last_record_offset.
    last_record_offset: i64,
    /// first is whether the current chunk is the first chunk of the record.
    first: bool,
    /// pending is whether a chunk is buffered but not yet written.
    pending: bool,
    /// err is any accumulated error.
    err: Option<RecordError>,
    /// buf is the buffer.
    buf: Box<[u8; BLOCK_SIZE]>,
    /// CRC function.
    crc: fn(&[u8]) -> u32,
}

impl<W: Write> Writer<W> {
    /// Returns a Writer for a new W&B LevelDB file.
    ///
    /// W&B LevelDB files start with a W&B header containing a version byte.
    ///
    /// Go: `NewWriterExt`. PARITY: Go runtime-detects whether `w` is an
    /// `io.Seeker` to compute the base offset; use
    /// [`Writer::new_ext_seekable`] for that behavior. This constructor uses
    /// base offset 0, like Go with a non-seekable writer.
    pub fn new_ext(w: W, algo: CrcAlgo, version: u8) -> Self {
        Self::with_base_offset(w, algo, version, 0)
    }

    fn with_base_offset(w: W, algo: CrcAlgo, version: u8, base_offset: i64) -> Self {
        let mut writer = Writer {
            w,
            seq: 0,
            i: 0,
            j: 0,
            written: 0,
            base_offset,
            block_number: 0,
            last_record_offset: -1,
            first: false,
            pending: false,
            err: None,
            buf: Box::new([0u8; BLOCK_SIZE]),
            crc: crc_fn(algo),
        };

        // W&B header: identifier.
        writer.buf[0..4].copy_from_slice(WANDB_HEADER_IDENT);

        // W&B header: little-endian encoding of the magic number.
        writer.buf[4] = (WANDB_HEADER_MAGIC & 0x00FF) as u8;
        writer.buf[5] = ((WANDB_HEADER_MAGIC & 0xFF00) >> 8) as u8;

        // W&B header: version.
        writer.buf[6] = version;

        // Advance j to indicate that 7 bytes in the buffer contain data.
        writer.j = 7;

        writer
    }

    /// Returns a shared reference to the underlying writer.
    pub fn get_ref(&self) -> &W {
        &self.w
    }

    /// Returns a mutable reference to the underlying writer.
    pub fn get_mut(&mut self) -> &mut W {
        &mut self.w
    }

    /// fillHeader fills in the header for the pending chunk.
    fn fill_header(&mut self, last: bool) {
        assert!(
            self.i + HEADER_SIZE <= self.j && self.j <= BLOCK_SIZE,
            "leveldb/record: bad writer state" // PARITY: Go panics here too.
        );
        if last {
            if self.first {
                self.buf[self.i + 6] = FULL_CHUNK_TYPE;
            } else {
                self.buf[self.i + 6] = LAST_CHUNK_TYPE;
            }
        } else if self.first {
            self.buf[self.i + 6] = FIRST_CHUNK_TYPE;
        } else {
            self.buf[self.i + 6] = MIDDLE_CHUNK_TYPE;
        }
        let checksum = (self.crc)(&self.buf[self.i + 6..self.j]);
        self.buf[self.i..self.i + 4].copy_from_slice(&checksum.to_le_bytes());
        let length = (self.j - self.i - HEADER_SIZE) as u16;
        self.buf[self.i + 4..self.i + 6].copy_from_slice(&length.to_le_bytes());
    }

    /// writeBlock writes the buffered block to the underlying writer, and
    /// reserves space for the next chunk's header.
    fn write_block(&mut self) {
        self.err = self
            .w
            .write_all(&self.buf[self.written..])
            .err()
            .map(RecordError::from);
        self.i = 0;
        self.j = HEADER_SIZE;
        self.written = 0;
        self.block_number += 1;
    }

    /// writePending finishes the current record and writes the buffer to the
    /// underlying writer.
    fn write_pending(&mut self) {
        if self.err.is_some() {
            return;
        }
        if self.pending {
            self.fill_header(true);
            self.pending = false;
        }
        self.err = self
            .w
            .write_all(&self.buf[self.written..self.j])
            .err()
            .map(RecordError::from);
        self.written = self.j;
    }

    /// Close finishes the current record and closes the writer.
    pub fn close(&mut self) -> Result<(), RecordError> {
        self.seq += 1;
        self.write_pending();
        if let Some(err) = &self.err {
            return Err(err.clone());
        }
        self.err = Some(RecordError::ClosedWriter);
        Ok(())
    }

    /// Flush finishes the current record, writes to the underlying writer,
    /// and flushes it.
    ///
    /// PARITY: Go only flushes if the writer implements
    /// `interface{ Flush() error }`; `io::Write::flush` is universal in Rust
    /// and a no-op for in-memory buffers, matching Go's `bytes.Buffer` path.
    pub fn flush(&mut self) -> Result<(), RecordError> {
        self.seq += 1;
        self.write_pending();
        if let Some(err) = &self.err {
            return Err(err.clone());
        }
        if let Err(e) = self.w.flush() {
            let err = RecordError::from(e);
            self.err = Some(err.clone());
            return Err(err);
        }
        Ok(())
    }

    /// Next returns a handle for the next record. The handle becomes stale
    /// after the next `close`, `flush` or `next` call, and should no longer
    /// be used.
    #[allow(clippy::should_implement_trait)] // Go: Writer.Next; not an Iterator.
    pub fn next(&mut self) -> Result<SingleWriter, RecordError> {
        self.seq += 1;
        if let Some(err) = &self.err {
            return Err(err.clone());
        }
        if self.pending {
            self.fill_header(true);
        }
        self.i = self.j;
        self.j += HEADER_SIZE;
        // Check if there is room in the block for the header.
        if self.j > BLOCK_SIZE {
            // Fill in the rest of the block with zeroes.
            self.buf[self.i..BLOCK_SIZE].fill(0);
            self.write_block();
            if let Some(err) = &self.err {
                return Err(err.clone());
            }
        }
        self.last_record_offset =
            self.base_offset + self.block_number * BLOCK_SIZE as i64 + self.i as i64;
        self.first = true;
        self.pending = true;
        Ok(SingleWriter { seq: self.seq })
    }

    /// LastRecordOffset returns the offset in the underlying writer of the
    /// last record so far - the one created by the most recent `next` call.
    /// It is the offset of the first chunk header, suitable to pass to
    /// [`Reader::seek_record`].
    ///
    /// If the writer was constructed with [`Writer::new_ext_seekable`], the
    /// return value is an absolute offset, regardless of whether the writer
    /// was initially at the zero position. Otherwise, the return value is a
    /// relative offset, being the number of bytes written between the
    /// constructor call and any records written prior to the last record.
    ///
    /// If there is no last record, i.e. nothing was written,
    /// LastRecordOffset will return [`RecordError::NoLastRecord`].
    pub fn last_record_offset(&self) -> Result<i64, RecordError> {
        if let Some(err) = &self.err {
            return Err(err.clone());
        }
        if self.last_record_offset < 0 {
            return Err(RecordError::NoLastRecord);
        }
        Ok(self.last_record_offset)
    }
}

impl<W: Write + Seek> Writer<W> {
    /// Like [`Writer::new_ext`], but queries the writer's current position to
    /// use as the base offset (falling back to 0 on error), mirroring Go's
    /// `NewWriterExt` behavior for writers that implement `io.Seeker`.
    pub fn new_ext_seekable(mut w: W, algo: CrcAlgo, version: u8) -> Self {
        let o = match w.stream_position() {
            Ok(o) => o as i64,
            Err(_) => 0,
        };
        Self::with_base_offset(w, algo, version, o)
    }
}

/// Handle to the record most recently returned by [`Writer::next`].
///
/// Go: `singleWriter`. See the module PARITY notes for why the parent is
/// passed to each call instead of being captured.
#[derive(Debug, Clone, Copy)]
pub struct SingleWriter {
    seq: i64,
}

impl SingleWriter {
    /// Go: `singleWriter.Write`.
    pub fn write<W: Write>(&self, w: &mut Writer<W>, p: &[u8]) -> Result<usize, RecordError> {
        if w.seq != self.seq {
            return Err(RecordError::StaleWriter);
        }
        if let Some(err) = &w.err {
            return Err(err.clone());
        }
        let n0 = p.len();
        let mut p = p;
        while !p.is_empty() {
            // Write a block, if it is full.
            if w.j == BLOCK_SIZE {
                w.fill_header(false);
                w.write_block();
                if let Some(err) = &w.err {
                    return Err(err.clone());
                }
                w.first = false;
            }
            // Copy bytes into the buffer.
            let n = p.len().min(BLOCK_SIZE - w.j);
            w.buf[w.j..w.j + n].copy_from_slice(&p[..n]);
            w.j += n;
            p = &p[n..];
        }
        Ok(n0)
    }
}

// Transliteration of core/pkg/leveldb/record_internal_test.go. Go case names
// are kept 1:1 in test fn names and sub-case strings.
#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::{Cell, RefCell};
    use std::io::Cursor;
    use std::rc::Rc;

    fn short(s: &str) -> String {
        if s.len() < 64 {
            return s.to_string();
        }
        format!(
            "{}...(skipping {} bytes)...{}",
            &s[..20],
            s.len() - 40,
            &s[s.len() - 20..]
        )
    }

    /// big returns a string of length n, composed of repetitions of partial.
    fn big(partial: &str, n: usize) -> String {
        partial.repeat(n / partial.len() + 1)[..n].to_string()
    }

    /// PARITY: the exact 100 values produced by Go's
    /// `rand.New(rand.NewSource(0)).Intn(2*blockSize + 16)` as consumed by
    /// TestRandom (record_internal_test.go:146). Go's `math/rand` (v1) source
    /// is deterministic and stable across Go versions, so embedding the
    /// sequence reproduces the same record-length corpus (chunk layouts,
    /// block splits) the Go spec exercises.
    #[rustfmt::skip]
    const GO_RAND_SEED0_INTN_2BLOCKSIZE_PLUS_16: [usize; 100] = [
        41146, 3714, 8425, 19946, 10331, 24880, 18959, 44741, 18456, 34864,
        4360, 22059, 52683, 908, 30696, 50558, 44207, 43906, 35682, 9118,
        61915, 3444, 35386, 36028, 29745, 63978, 11520, 54960, 4815, 47196,
        34493, 8436, 24833, 49948, 7894, 15201, 56312, 59998, 12317, 11074,
        11391, 21868, 5044, 394, 61887, 49607, 28932, 19016, 52302, 3833,
        44542, 25872, 49450, 44816, 34467, 2468, 22921, 48246, 35868, 62920,
        56214, 20763, 29213, 56490, 8494, 16435, 30503, 5856, 19593, 6833,
        36127, 8806, 5236, 37399, 23378, 41317, 11833, 21212, 24895, 34427,
        19070, 21446, 52916, 50891, 58260, 52273, 30170, 56674, 18756, 39510,
        36244, 3384, 65264, 6420, 45848, 37906, 13825, 53044, 17522, 245,
    ];

    /// PARITY: the exact 100 values produced by Go's
    /// `rand.New(rand.NewSource(1)).Intn(3*blockSize)` as consumed by
    /// TestNonExhaustiveRead (record_internal_test.go:250).
    #[rustfmt::skip]
    const GO_RAND_SEED1_INTN_3BLOCKSIZE: [usize; 100] = [
        545, 72207, 52679, 1211, 34177, 86406, 84793, 21164, 32584, 51108,
        97478, 23215, 65442, 57329, 8536, 5402, 95883, 89237, 81701, 35810,
        67343, 35034, 53864, 40594, 17535, 85291, 20527, 85240, 52278, 6135,
        2869, 28536, 72155, 64271, 47013, 67916, 77865, 50167, 49917, 84882,
        5773, 49810, 25546, 9027, 88561, 80787, 66526, 15076, 33151, 74841,
        74517, 50761, 61941, 91287, 7336, 89617, 96968, 37626, 96103, 30635,
        33539, 92190, 30909, 14748, 5482, 59300, 8681, 77954, 3743, 3362,
        36427, 83688, 33002, 9974, 16743, 59430, 457, 93703, 30844, 48308,
        21279, 21369, 11521, 71581, 86921, 3115, 70121, 18323, 22019, 9394,
        69566, 6232, 45954, 40435, 44580, 54535, 1368, 94371, 74125, 62846,
    ];

    /// Shared byte buffer standing in for Go's `*bytes.Buffer`, which tests
    /// inspect while a Writer still holds it.
    #[derive(Clone, Default)]
    struct SharedBuf(Rc<RefCell<Vec<u8>>>);

    impl Write for SharedBuf {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.0.borrow_mut().extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    impl SharedBuf {
        fn len(&self) -> usize {
            self.0.borrow().len()
        }

        fn to_vec(&self) -> Vec<u8> {
            self.0.borrow().clone()
        }
    }

    /// Go: `io.ReadFull(rr, p)`.
    fn read_full_record<R: Read>(
        rr: &SingleReader,
        r: &mut Reader<R>,
        p: &mut [u8],
    ) -> Result<(), RecordError> {
        let mut n = 0;
        while n < p.len() {
            n += rr.read(r, &mut p[n..])?;
        }
        Ok(())
    }

    /// TestZeroBlocks tests that reading nothing but all-zero blocks gives
    /// io.EOF. This includes decoding an empty stream.
    #[test]
    fn test_zero_blocks() {
        for i in 0..3usize {
            let mut r = Reader::new(Cursor::new(vec![0u8; i * BLOCK_SIZE]));
            match r.next() {
                Err(RecordError::Eof) => {}
                other => panic!("{i} blocks: got {other:?}, want EOF"),
            }
        }
    }

    fn test_generator(reset: &mut dyn FnMut(), gen_fn: &mut dyn FnMut() -> Option<String>) {
        let mut buf: Vec<u8> = Vec::new();
        let mut offsets: Vec<i64> = Vec::new();

        reset();
        {
            let mut w = Writer::new_ext(&mut buf, CrcAlgo::Custom, 0);
            while let Some(s) = gen_fn() {
                let ww = w.next().expect("writer.Next");
                ww.write(&mut w, s.as_bytes()).expect("Write");
                let offset = w.last_record_offset().expect("writer.LastRecordOffset");
                offsets.push(offset);
            }
            w.close().expect("Close");
        }

        reset();
        let mut r = Reader::new(Cursor::new(&buf[..]));
        let mut offsets = offsets.into_iter();
        while let Some(s) = gen_fn() {
            let expected_offset = offsets.next().unwrap();

            let offset = r.next_offset();
            let rr = r.next().expect("reader.Next");

            assert_eq!(
                offset, expected_offset,
                "got offset {offset}, expected {expected_offset}"
            );

            let x = rr.read_all(&mut r).expect("ReadAll");
            let x = String::from_utf8(x).expect("record is not UTF-8");
            assert_eq!(x, s, "got {:?}, want {:?}", short(&x), short(&s));
        }
        match r.next() {
            Err(RecordError::Eof) => {}
            other => panic!("got {other:?}, want EOF"),
        }
    }

    fn test_literals(s: &[&str]) {
        let i = Cell::new(0usize);
        test_generator(&mut || i.set(0), &mut || {
            if i.get() == s.len() {
                return None;
            }
            i.set(i.get() + 1);
            Some(s[i.get() - 1].to_string())
        });
    }

    #[test]
    fn test_many() {
        const N: usize = 100_000; // Go: 1e5
        let i = Cell::new(0usize);
        test_generator(&mut || i.set(0), &mut || {
            if i.get() == N {
                return None;
            }
            i.set(i.get() + 1);
            Some(format!("{}.", i.get() - 1))
        });
    }

    #[test]
    fn test_random() {
        const N: usize = 100; // Go: 1e2
        let i = Cell::new(0usize);
        test_generator(&mut || i.set(0), &mut || {
            // Go: `i, r = 0, rand.New(rand.NewSource(0))` on reset;
            // `r.Intn(2*blockSize + 16)` per record (embedded as a fixture).
            if i.get() == N {
                return None;
            }
            i.set(i.get() + 1);
            let count = GO_RAND_SEED0_INTN_2BLOCKSIZE_PLUS_16[i.get() - 1];
            Some(String::from_utf8(vec![i.get() as u8; count]).unwrap())
        });
    }

    #[test]
    fn test_basic() {
        let (a, b, c) = ("a".repeat(1000), "b".repeat(97270), "c".repeat(8000));
        test_literals(&[&a, &b, &c]);
    }

    #[test]
    fn test_boundary() {
        for i in (BLOCK_SIZE - 16)..(BLOCK_SIZE + 16) {
            let s0 = big("abcd", i);
            for j in (BLOCK_SIZE - 16)..(BLOCK_SIZE + 16) {
                let s1 = big("ABCDE", j);
                test_literals(&[&s0, &s1]);
                test_literals(&[&s0, "", &s1]);
                test_literals(&[&s0, "x", &s1]);
            }
        }
    }

    #[test]
    fn test_flush() {
        let buf = SharedBuf::default();
        let mut w = Writer::new_ext(buf.clone(), CrcAlgo::Custom, 0);
        // Write a couple of records. Everything should still be held
        // in the record.Writer buffer, so that buf.len should be 0.
        let w0 = w.next().unwrap();
        let _ = w0.write(&mut w, b"0");
        let w1 = w.next().unwrap();
        let _ = w1.write(&mut w, b"11");
        assert_eq!(buf.len(), 0, "buffer length #0");
        // Flush the record.Writer buffer, which should yield 24 bytes.
        // 24 = 7 + 2*7 + 1 + 2, which is a W&B header, two LevelDB headers,
        // and 1 + 2 payload bytes.
        w.flush().unwrap();
        assert_eq!(buf.len(), 24, "buffer length #1");
        // Do another write, one that isn't large enough to complete the block.
        // The write should not have flowed through to buf.
        let w2 = w.next().unwrap();
        let _ = w2.write(&mut w, &[b'2'].repeat(10000));
        assert_eq!(buf.len(), 24, "buffer length #2");
        // Flushing should get us up to 10031 bytes written.
        // 10031 = 24 + 7 + 10000.
        w.flush().unwrap();
        assert_eq!(buf.len(), 10031, "buffer length #3");
        // Do a bigger write, one that completes the current block.
        // We should now have 32768 bytes (a complete block), without
        // an explicit flush.
        let w3 = w.next().unwrap();
        let _ = w3.write(&mut w, &[b'3'].repeat(40000));
        assert_eq!(buf.len(), 32768, "buffer length #4");
        // Flushing should get us up to 50045 bytes written.
        // 50045 = 10031 + 2*7 + 40000. There are two headers because
        // the one record was split into two chunks.
        w.flush().unwrap();
        assert_eq!(buf.len(), 50045, "buffer length #5");
        // Check that reading those records give the right lengths.
        let mut r = Reader::new(Cursor::new(buf.to_vec()));
        let wants: [usize; 4] = [1, 2, 10000, 40000];
        for (i, want) in wants.into_iter().enumerate() {
            let rr = r.next().unwrap();
            let n = rr
                .read_all(&mut r)
                .unwrap_or_else(|e| panic!("read #{i}: {e}"))
                .len();
            assert_eq!(n, want, "read #{i}: got {n} bytes want {want}");
        }
    }

    #[test]
    #[allow(clippy::needless_range_loop)] // PARITY: keep Go's `for i := range n` shape.
    fn test_non_exhaustive_read() {
        const N: usize = 100;
        let mut buf: Vec<u8> = Vec::new();
        let mut p = [0u8; 10];

        {
            let mut w = Writer::new_ext(&mut buf, CrcAlgo::Custom, 0);
            for i in 0..N {
                // Go: `rnd.Intn(3*blockSize)` with rand.NewSource(1),
                // embedded as a fixture.
                let length = p.len() + GO_RAND_SEED1_INTN_3BLOCKSIZE[i];
                let mut s = String::new();
                s.push(char::from(i as u8));
                s.push_str("123456789abcdefgh");
                let ww = w.next().unwrap();
                let _ = ww.write(&mut w, big(&s, length).as_bytes());
            }
            w.close().expect("Close");
        }

        let mut r = Reader::new(Cursor::new(&buf[..]));
        for i in 0..N {
            let rr = r.next().unwrap();
            read_full_record(&rr, &mut r, &mut p).expect("ReadFull");
            let mut want = String::new();
            want.push(char::from(i as u8));
            want.push_str("123456789");
            assert_eq!(&p[..], want.as_bytes(), "read #{i}");
        }
    }

    #[test]
    fn test_truncation_eof() {
        // Test that truncating a block at any point leads to either
        // EOF or ErrUnexpectedEOF when reading.

        // test_data contains two records: the first is 1 byte long and consists
        // of a single full chunk, and the second takes up 32 KiB so that it
        // ends in the second block.
        let mut test_data: Vec<u8> = Vec::new();
        {
            let mut w = Writer::new_ext(&mut test_data, CrcAlgo::Custom, 0);

            let w0 = w.next().unwrap();
            w0.write(&mut w, b"x").unwrap();

            let w1 = w.next().unwrap();
            w1.write(&mut w, big("abcd", 32 * 1024).as_bytes()).unwrap();

            w.close().unwrap();
        }

        // "0 is EOF"
        {
            let mut r = Reader::new(Cursor::new(&test_data[..0]));
            let err = r.next().unwrap_err();
            assert!(matches!(err, RecordError::Eof), "0 is EOF: got {err:?}");
        }

        // "inside WB header is EOF"
        {
            let mut r = Reader::new(Cursor::new(&test_data[..1]));
            let err = r.next().unwrap_err();
            assert!(
                matches!(err, RecordError::Eof),
                "inside WB header is EOF: got {err:?}"
            );
        }

        // "between records is EOF"
        {
            // Truncate before the first record.
            let mut r = Reader::new(Cursor::new(&test_data[..7]));
            let err = r.next().unwrap_err();
            assert!(
                matches!(err, RecordError::Eof),
                "between records is EOF: got {err:?}"
            );

            // Truncate before the second record.
            let mut r = Reader::new(Cursor::new(&test_data[..15]));
            r.next().expect("Next");
            let err = r.next().unwrap_err();
            assert!(
                matches!(err, RecordError::Eof),
                "between records is EOF: got {err:?}"
            );
        }

        // The first record is a single 8-byte chunk; just test all positions.
        for i in 0..7usize {
            // "inside chunk is ErrUnexpectedEOF (offset {i})"
            let mut r = Reader::new(Cursor::new(&test_data[..7 + 1 + i]));
            let err = r.next().unwrap_err();
            assert!(
                matches!(err, RecordError::UnexpectedEof),
                "inside chunk is ErrUnexpectedEOF (offset {i}): got {err:?}"
            );
        }

        // "at boundary inside record is ErrUnexpectedEOF"
        {
            let mut r = Reader::new(Cursor::new(&test_data[..32 * 1024]));

            // Seek the second record.
            r.seek_record(7 + 7 + 1) // W&B header; 1st chunk header & content
                .expect("SeekRecord");

            // No error in next because first chunk is fully included.
            let rr = r.next().expect("Next");

            // But reading should error out, since the record is truncated.
            let err = rr.read_all(&mut r).unwrap_err();
            assert!(
                matches!(err, RecordError::UnexpectedEof),
                "at boundary inside record is ErrUnexpectedEOF: got {err:?}"
            );
        }
    }

    #[test]
    fn test_stale_reader() {
        let mut buf: Vec<u8> = Vec::new();
        {
            let mut w = Writer::new_ext(&mut buf, CrcAlgo::Custom, 0);
            let w0 = w.next().expect("writer.Next");
            let _ = w0.write(&mut w, b"0");
            let w1 = w.next().expect("writer.Next");
            let _ = w1.write(&mut w, b"11");
            w.close().expect("Close");
        }

        let mut r = Reader::new(Cursor::new(&buf[..]));
        let r0 = r.next().expect("reader.Next");
        let r1 = r.next().expect("reader.Next");
        let mut p = [0u8; 1];
        match r0.read(&mut r, &mut p) {
            Err(err) if err.to_string().contains("stale") => {}
            other => panic!("stale read #0: unexpected result: {other:?}"),
        }
        r1.read(&mut r, &mut p)
            .unwrap_or_else(|e| panic!("fresh read #1: got {e} want no error"));
        assert_eq!(p[0], b'1', "fresh read #1: byte contents");
    }

    #[test]
    fn test_stale_writer() {
        let buf = SharedBuf::default();

        let mut w = Writer::new_ext(buf, CrcAlgo::Custom, 0);
        let w0 = w.next().expect("writer.Next");
        let w1 = w.next().expect("writer.Next");
        match w0.write(&mut w, b"0") {
            Err(err) if err.to_string().contains("stale") => {}
            other => panic!("stale write #0: unexpected result: {other:?}"),
        }
        w1.write(&mut w, b"11")
            .unwrap_or_else(|e| panic!("fresh write #1: got {e} want no error"));
        w.flush().expect("flush");
        match w1.write(&mut w, b"0") {
            Err(err) if err.to_string().contains("stale") => {}
            other => panic!("stale write #1: unexpected result: {other:?}"),
        }
    }

    struct TestRecords {
        /// The raw value of each record.
        records: Vec<Vec<u8>>,
        /// The offset of each record within buf, derived from
        /// writer.LastRecordOffset.
        offsets: Vec<i64>,
        /// The serialized records form of all records.
        buf: Vec<u8>,
    }

    /// makeTestRecords generates test records of specified lengths.
    /// The first record will consist of repeating 0x00 bytes, the next record
    /// of 0x01 bytes, and so forth. The values will loop back to 0x00 after
    /// 0xff.
    fn make_test_records(record_lengths: &[usize]) -> Result<TestRecords, RecordError> {
        let records: Vec<Vec<u8>> = record_lengths
            .iter()
            .enumerate()
            .map(|(i, &n)| vec![i as u8; n])
            .collect();
        let mut offsets = vec![0i64; record_lengths.len()];

        let mut buf: Vec<u8> = Vec::new();
        {
            let mut w = Writer::new_ext(&mut buf, CrcAlgo::Custom, 0);
            for (i, rec) in records.iter().enumerate() {
                let w_rec = w.next()?;

                // Alternate between one big write and many small writes.
                let mut rec: &[u8] = rec;
                let c_size = if i & 1 == 0 { rec.len() } else { 8 };
                while rec.len() > c_size {
                    w_rec.write(&mut w, &rec[..c_size])?;
                    rec = &rec[c_size..];
                }
                w_rec.write(&mut w, rec)?;

                offsets[i] = w.last_record_offset()?;
            }

            w.close()?;
        }

        Ok(TestRecords {
            records,
            offsets,
            buf,
        })
    }

    /// corruptBlock corrupts the checksum of the record that starts at the
    /// specified block offset. The number of the block offset is 0 based.
    fn corrupt_block(buf: &mut [u8], block_num: usize) {
        // Ensure we always permute at least 1 byte of the checksum.
        if buf[BLOCK_SIZE * block_num] == 0x00 {
            buf[BLOCK_SIZE * block_num] = 0xff;
        } else {
            buf[BLOCK_SIZE * block_num] = 0x00;
        }

        buf[BLOCK_SIZE * block_num + 1] = 0x00;
        buf[BLOCK_SIZE * block_num + 2] = 0x00;
        buf[BLOCK_SIZE * block_num + 3] = 0x00;
    }

    #[test]
    fn test_recover_no_op() {
        let recs = make_test_records(&[
            BLOCK_SIZE - HEADER_SIZE,
            BLOCK_SIZE - HEADER_SIZE,
            BLOCK_SIZE - HEADER_SIZE,
        ])
        .expect("makeTestRecords");

        let mut r = Reader::new(Cursor::new(&recs.buf[..]));
        let res = r.next();
        assert!(
            res.is_ok() && r.err.is_none(),
            "reader.Next: {res:?} reader.err: {:?}",
            r.err
        );

        let (seq, i, j, n) = (r.seq, r.i, r.j, r.n);

        // Should be a no-op since r.err is None.
        r.recover();

        // r.err was None, nothing should have changed.
        assert!(
            seq == r.seq && i == r.i && j == r.j && n == r.n,
            "reader.Recover when no error existed, was not a no-op"
        );
    }

    #[test]
    fn test_basic_recover() {
        let mut recs = make_test_records(&[
            BLOCK_SIZE - HEADER_SIZE - WANDB_HEADER_LENGTH,
            BLOCK_SIZE - HEADER_SIZE,
            BLOCK_SIZE - HEADER_SIZE,
        ])
        .expect("makeTestRecords");

        // Corrupt the checksum of the second record r1 in our file.
        corrupt_block(&mut recs.buf, 1);

        let mut r = Reader::new(Cursor::new(&recs.buf[..]));

        // The first record r0 should be read just fine.
        let r0 = r.next().expect("Next");
        let r0_data = r0.read_all(&mut r).expect("ReadAll");
        assert_eq!(r0_data, recs.records[0], "Unexpected output in r0's data");

        // The next record should have a checksum mismatch.
        let err = r
            .next()
            .expect_err("Expected an error while reading a corrupted record");
        assert!(
            err.to_string().contains("checksum mismatch"),
            "Unexpected error returned: {err}"
        );

        // Recover from that checksum mismatch.
        r.recover();
        let current_offset = r.get_ref().position();
        assert_eq!(current_offset, (BLOCK_SIZE * 2) as u64, "current offset");

        // The third record r2 should be read just fine.
        let r2 = r.next().expect("Next");
        let r2_data = r2.read_all(&mut r).expect("ReadAll");
        assert_eq!(r2_data, recs.records[2], "Unexpected output in r2's data");
    }

    #[test]
    fn test_recover_single_block() {
        // The first record will be BLOCK_SIZE * 3 bytes long. Since each block
        // has a 7 byte header, the first record will roll over into 4 blocks.
        let mut recs =
            make_test_records(&[BLOCK_SIZE * 3, BLOCK_SIZE - HEADER_SIZE, BLOCK_SIZE / 2])
                .expect("makeTestRecords");

        // Corrupt the checksum for the portion of the first record that exists
        // in the 4th block.
        corrupt_block(&mut recs.buf, 3);

        // The first record should fail, but only when we read deeper beyond
        // the first block.
        let mut r = Reader::new(Cursor::new(&recs.buf[..]));
        let r0 = r.next().expect("Next");

        // Reading deeper should yield a checksum mismatch.
        let err = r0
            .read_all(&mut r)
            .expect_err("Expected a checksum mismatch error, got nil");
        assert!(
            err.to_string().contains("checksum mismatch"),
            "Unexpected error returned: {err}"
        );

        // Recover from that checksum mismatch.
        r.recover();

        // All of the data in the second record r1 is lost because the first
        // record r0 shared a partial block with it. The second record also
        // overlapped into the block with the third record r2. Recovery should
        // jump to that block, skipping over the end of the second record and
        // start parsing the third record.
        let r2 = r.next().expect("Next");
        let r2_data = r2.read_all(&mut r).unwrap_or_default();
        assert_eq!(r2_data, recs.records[2], "Unexpected output in r2's data");
    }

    #[test]
    fn test_recover_multiple_blocks() {
        let mut recs = make_test_records(&[
            // The first record will consume 3 entire blocks but a fraction of
            // the 4th.
            (BLOCK_SIZE - WANDB_HEADER_LENGTH) + BLOCK_SIZE * 2,
            // The second record will completely fill the remainder of the 4th
            // block.
            3 * (BLOCK_SIZE - HEADER_SIZE) - 2 * BLOCK_SIZE - 2 * HEADER_SIZE,
            // Consume the entirety of the 5th block.
            BLOCK_SIZE - HEADER_SIZE,
            // Consume the entirety of the 6th block.
            BLOCK_SIZE - HEADER_SIZE,
            // Consume roughly half of the 7th block.
            BLOCK_SIZE / 2,
        ])
        .expect("makeTestRecords");

        // Corrupt the checksum for the portion of the first record that exists
        // in the 4th block.
        corrupt_block(&mut recs.buf, 3);

        // Now corrupt the two blocks in a row that correspond to
        // recs.records[2..4].
        corrupt_block(&mut recs.buf, 4);
        corrupt_block(&mut recs.buf, 5);

        // The first record should fail, but only when we read deeper beyond
        // the first block.
        let mut r = Reader::new(Cursor::new(&recs.buf[..]));
        let r0 = r.next().expect("Next");

        // Reading deeper should yield a checksum mismatch.
        let err = r0
            .read_all(&mut r)
            .expect_err("Expected a checksum mismatch error, got nil");
        assert!(
            err.to_string().contains("checksum mismatch"),
            "Unexpected error returned: {err}"
        );

        // Recover from that checksum mismatch.
        r.recover();

        // All of the data in the second record is lost because the first
        // record shared a partial block with it. The following two records
        // have corrupted checksums as well, so the call above to r.recover
        // should result in r.next() being a reader to the 5th record.
        let r4 = r.next().expect("Next");

        let r4_data = r4.read_all(&mut r).unwrap_or_default();
        assert_eq!(r4_data, recs.records[4], "Unexpected output in r4's data");
    }

    /// verifyLastBlockRecover reads each record from recs expecting that the
    /// last record will be corrupted. It will then try recover and verify that
    /// EOF is returned.
    fn verify_last_block_recover(recs: &TestRecords) -> Result<(), String> {
        let mut r = Reader::new(Cursor::new(&recs.buf[..]));
        // Loop to one element larger than the number of records to verify EOF.
        for i in 0..recs.records.len() + 1 {
            let res = r.next();
            if i == recs.records.len() - 1 {
                if res.is_ok() {
                    return Err("Expected a checksum mismatch error, got nil".to_string());
                }
                r.recover();
            } else if i == recs.records.len() {
                match res {
                    Err(RecordError::Eof) => {}
                    other => return Err(format!("Expected io.EOF, got {other:?}")),
                }
            } else if let Err(err) = res {
                return Err(format!("Next: {err}"));
            }
        }
        Ok(())
    }

    #[test]
    fn test_recover_last_partial_block() {
        let mut recs = make_test_records(&[
            // The first record will consume 3 entire blocks but a fraction of
            // the 4th.
            BLOCK_SIZE * 3,
            // The second record will completely fill the remainder of the 4th
            // block.
            3 * (BLOCK_SIZE - HEADER_SIZE) - 2 * BLOCK_SIZE - 2 * HEADER_SIZE,
            // Consume roughly half of the 5th block.
            BLOCK_SIZE / 2,
        ])
        .expect("makeTestRecords");

        // Corrupt the 5th block.
        corrupt_block(&mut recs.buf, 4);

        // Verify recover works when the last block is corrupted.
        verify_last_block_recover(&recs).unwrap_or_else(|e| panic!("verifyLastBlockRecover: {e}"));
    }

    #[test]
    fn test_recover_last_complete_block() {
        let mut recs = make_test_records(&[
            // The first record will consume 3 entire blocks but a fraction of
            // the 4th.
            BLOCK_SIZE * 3,
            // The second record will completely fill the remainder of the 4th
            // block.
            3 * (BLOCK_SIZE - HEADER_SIZE) - 2 * BLOCK_SIZE - 2 * HEADER_SIZE,
            // Consume the entire 5th block.
            BLOCK_SIZE - HEADER_SIZE,
        ])
        .expect("makeTestRecords");

        // Corrupt the 5th block.
        corrupt_block(&mut recs.buf, 4);

        // Verify recover works when the last block is corrupted.
        verify_last_block_recover(&recs).unwrap_or_else(|e| panic!("verifyLastBlockRecover: {e}"));
    }

    #[test]
    fn test_seek_record() {
        let recs = make_test_records(&[
            // The first record will consume 3 entire blocks but a fraction of
            // the 4th.
            (BLOCK_SIZE - WANDB_HEADER_LENGTH) + BLOCK_SIZE * 2,
            // The second record will completely fill the remainder of the 4th
            // block.
            3 * (BLOCK_SIZE - HEADER_SIZE) - 2 * BLOCK_SIZE - 2 * HEADER_SIZE,
            // Consume the entirety of the 5th block.
            BLOCK_SIZE - HEADER_SIZE,
            // Consume the entirety of the 6th block.
            BLOCK_SIZE - HEADER_SIZE,
            // Consume roughly half of the 7th block.
            BLOCK_SIZE / 2,
        ])
        .expect("makeTestRecords");

        let mut r = Reader::new(Cursor::new(&recs.buf[..]));
        // Seek to a valid block offset, but within a multiblock record. This
        // should cause the next call to next after seek_record to return the
        // next valid FIRST/FULL chunk of the subsequent record.
        r.seek_record(BLOCK_SIZE as i64).expect("SeekRecord");
        let rec = r.next().expect("Next");
        let r_data = rec.read_all(&mut r).unwrap_or_default();
        assert_eq!(
            r_data, recs.records[1],
            "Unexpected output in record 1's data"
        );

        // Seek 3 bytes into the second block, which is still in the middle of
        // the first record, but not at a valid chunk boundary. Should result
        // in an error upon calling r.next.
        r.seek_record(BLOCK_SIZE as i64 + 3).expect("SeekRecord");
        assert!(
            r.next().is_err(),
            "Expected an error seeking to an invalid chunk boundary"
        );
        r.recover();

        fn check<R: Read + Seek>(r: &mut Reader<R>, recs: &TestRecords, start: usize) {
            for i in start..recs.records.len() {
                let rec = r.next().expect("Next");

                let r_data = rec.read_all(r).unwrap_or_default();
                assert_eq!(
                    r_data, recs.records[i],
                    "Unexpected output in record #{i}'s data"
                );
            }
        }

        // Seek to the fifth block and verify all records can be read as
        // appropriate.
        r.seek_record(BLOCK_SIZE as i64 * 4).expect("SeekRecord");
        check(&mut r, &recs, 2);

        // Seek back to the fourth block, and read all subsequent records and
        // verify them.
        r.seek_record(BLOCK_SIZE as i64 * 3).expect("SeekRecord");
        check(&mut r, &recs, 1);

        // Now seek past the end of the file and verify it does not cause an
        // error.
        r.seek_record(1 << 20)
            .unwrap_or_else(|e| panic!("Seeking past EOF returned unexpected error: {e}"));

        // Reading after the end of the file should return EOF.
        match r.next() {
            Ok(_) => panic!("Reading past EOF did not return EOF"),
            Err(RecordError::Eof) => {}
            Err(err) => panic!("Reading past EOF returned unexpected error: {err}"),
        }

        r.recover(); // Verify recovery works.

        // Validate the current records are returned after seeking to a valid
        // offset.
        r.seek_record(BLOCK_SIZE as i64 * 4).expect("SeekRecord");
        check(&mut r, &recs, 2);
    }

    #[test]
    fn test_last_record_offset() {
        let recs = make_test_records(&[
            // The first record will consume 3 entire blocks but a fraction of
            // the 4th.
            (BLOCK_SIZE - WANDB_HEADER_LENGTH) + BLOCK_SIZE * 2,
            // The second record will completely fill the remainder of the 4th
            // block.
            3 * (BLOCK_SIZE - HEADER_SIZE) - 2 * BLOCK_SIZE - 2 * HEADER_SIZE,
            // Consume the entirety of the 5th block.
            BLOCK_SIZE - HEADER_SIZE,
            // Consume the entirety of the 6th block.
            BLOCK_SIZE - HEADER_SIZE,
            // Consume roughly half of the 7th block.
            BLOCK_SIZE / 2,
        ])
        .expect("makeTestRecords");

        let wants: [i64; 5] = [7, 98332, 131072, 163840, 196608];
        for (i, &got) in recs.offsets.iter().enumerate() {
            assert_eq!(got, wants[i], "record #{i}");
        }
    }

    #[test]
    fn test_no_last_record_offset() {
        let mut w = Writer::new_ext(Vec::<u8>::new(), CrcAlgo::Custom, 0);

        match w.last_record_offset() {
            Err(RecordError::NoLastRecord) => {}
            other => panic!("Expected ErrNoLastRecord, got: {other:?}"),
        }

        w.flush().unwrap();

        match w.last_record_offset() {
            Err(RecordError::NoLastRecord) => {}
            other => panic!("LastRecordOffset: got: {other:?}, want ErrNoLastRecord"),
        }

        let writer = w.next().unwrap();

        writer.write(&mut w, b"testrecord").unwrap();

        let off = w
            .last_record_offset()
            .unwrap_or_else(|e| panic!("LastRecordOffset: {e}"));
        assert_eq!(
            off, WANDB_HEADER_LENGTH as i64,
            "LastRecordOffset: got {off}, want {WANDB_HEADER_LENGTH}"
        );
    }

    #[test]
    fn test_verify_wandb_header_good() {
        let data = b":W&B\xE1\xBE\x0Dleveldb stuff";
        let mut r = Reader::new(Cursor::new(&data[..]));

        r.verify_wandb_header(0x0D)
            .unwrap_or_else(|e| panic!("unexpected error: {e}"));
    }

    #[test]
    fn test_verify_wandb_header_too_short() {
        let data = b"short";
        let mut r = Reader::new(Cursor::new(&data[..]));

        let err = r.verify_wandb_header(0).unwrap_err();

        assert!(
            matches!(err, RecordError::UnexpectedEof),
            "wrong error: {err:?}"
        );
    }

    #[test]
    fn test_verify_wandb_header_invalid_ident() {
        let data = b"oops123";
        let mut r = Reader::new(Cursor::new(&data[..]));

        let err = r.verify_wandb_header(0).unwrap_err();

        assert!(
            err.to_string()
                .contains(r#"invalid W&B identifier: 6F6F7073 ("oops")"#),
            "wrong error: {err}"
        );
    }

    #[test]
    fn test_verify_wandb_header_invalid_magic() {
        let data = b":W&Bbad";
        let mut r = Reader::new(Cursor::new(&data[..]));

        let err = r.verify_wandb_header(0).unwrap_err();

        assert!(
            err.to_string().contains("invalid W&B magic"),
            "wrong error: {err}"
        );
    }

    #[test]
    fn test_verify_wandb_header_invalid_version() {
        let data = b":W&B\xE1\xBE\x01";
        let mut r = Reader::new(Cursor::new(&data[..]));

        let err = r.verify_wandb_header(0).unwrap_err();

        assert!(
            err.to_string().contains("expected W&B version 0 but got 1"),
            "wrong error: {err}"
        );
    }

    // Not in the Go test file: byte-exact stream check against the Go spec.
    // Expected hex dumps were generated by running core/pkg/leveldb directly
    // (records "a" then "bb", version byte 3, for both CRC algorithms).
    #[test]
    fn test_stream_bytes_match_go_oracle() {
        for (algo, want_hex) in [
            (
                CrcAlgo::Custom,
                "3A572642E1BE03B5CD0BA201000161DBAE76310200016262",
            ),
            (
                CrcAlgo::Ieee,
                "3A572642E1BE03707277620100016174BAF40A0200016262",
            ),
        ] {
            let mut buf: Vec<u8> = Vec::new();
            {
                let mut w = Writer::new_ext(&mut buf, algo, 3);
                let w0 = w.next().unwrap();
                w0.write(&mut w, b"a").unwrap();
                let w1 = w.next().unwrap();
                w1.write(&mut w, b"bb").unwrap();
                w.close().unwrap();
            }
            assert_eq!(hex_upper(&buf), want_hex, "algo {algo:?}");
        }
    }
}
