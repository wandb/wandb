//! Reader for W&B transaction logs (LevelDB record format variant).
//!
//! The stream is divided into 32 KiB blocks, each containing tightly packed
//! chunks that never cross block boundaries. Every chunk has a 7-byte header
//! (4-byte CRC32/IEEE checksum, 2-byte little-endian length, 1-byte type)
//! followed by a payload; the checksum covers the type byte and payload.
//!
//! W&B customizes the format with a 7-byte file header (":W&B" + magic +
//! version), which shortens the first block.

use std::io::{self, Read, Seek, SeekFrom};

const FULL_CHUNK: u8 = 1;
const FIRST_CHUNK: u8 = 2;
const MIDDLE_CHUNK: u8 = 3;
const LAST_CHUNK: u8 = 4;

const BLOCK_SIZE: usize = 32 * 1024;
const HEADER_SIZE: usize = 7;

const WANDB_IDENT: &[u8; 4] = b":W&B";
const WANDB_MAGIC: u16 = 0xBEE1;
const WANDB_HEADER_LEN: usize = 7;

/// The version byte written into `.wandb` file headers.
pub const WANDB_STORE_VERSION: u8 = 0;

/// Errors from the record reader.
#[derive(Debug)]
pub enum Error {
    /// Clean end of data; more may be appended later for live files.
    Eof,
    /// Data ended mid-record; more may be appended later for live files.
    UnexpectedEof,
    /// Unrecoverable data corruption or I/O failure.
    Corrupt(String),
    Io(io::Error),
}

impl Error {
    /// True if the error may be resolved by appending more data to the file.
    pub fn is_retryable(&self) -> bool {
        matches!(self, Error::Eof | Error::UnexpectedEof)
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Eof => write!(f, "EOF"),
            Error::UnexpectedEof => write!(f, "unexpected EOF"),
            Error::Corrupt(msg) => write!(f, "leveldb/record: {msg}"),
            Error::Io(e) => write!(f, "I/O error: {e}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}

/// Internal marker for zeroed blocks (mmap padding).
struct ZeroChunk;

/// Reads records from an underlying seekable reader.
pub struct RecordReader<R: Read + Seek> {
    r: R,
    /// Start position of the current block in the reader.
    block_offset: i64,
    /// `buf[i..j]` is the unread portion of the current chunk's payload.
    i: usize,
    j: usize,
    /// Offset of the next chunk from the start of the current block.
    next_chunk_start: usize,
    /// Number of valid bytes in `buf`.
    n: usize,
    recovering: bool,
    /// Whether the current chunk is the last chunk of the record.
    last: bool,
    /// Sticky error state; `Eof`/`UnexpectedEof` are cleared by `seek_record`.
    failed: Option<ErrorKind>,
    buf: Box<[u8; BLOCK_SIZE]>,
}

#[derive(Clone, Copy, PartialEq)]
enum ErrorKind {
    Eof,
    UnexpectedEof,
    Corrupt,
}

impl<R: Read + Seek> RecordReader<R> {
    pub fn new(r: R) -> Self {
        Self {
            r,
            block_offset: 0,
            i: 0,
            j: 0,
            next_chunk_start: WANDB_HEADER_LEN,
            n: 0,
            recovering: false,
            last: false,
            failed: None,
            buf: Box::new([0u8; BLOCK_SIZE]),
        }
    }

    /// Checks for a W&B header with the expected version.
    /// The reader must be positioned at the start.
    pub fn verify_wandb_header(&mut self, expected_version: u8) -> Result<(), Error> {
        if self.block_offset != 0 {
            return Err(Error::Corrupt("reader not in first block".into()));
        }
        if self.n == 0 {
            self.read_block()?;
        }
        if self.n < WANDB_HEADER_LEN {
            return Err(Error::UnexpectedEof);
        }

        if &self.buf[0..4] != WANDB_IDENT {
            return Err(Error::Corrupt(format!(
                "invalid W&B identifier: {:X?}",
                &self.buf[0..4]
            )));
        }
        let magic = u16::from(self.buf[4]) | (u16::from(self.buf[5]) << 8);
        if magic != WANDB_MAGIC {
            return Err(Error::Corrupt(format!("invalid W&B magic: {magic:X}")));
        }
        if self.buf[6] != expected_version {
            return Err(Error::Corrupt(format!(
                "expected W&B version {expected_version} but got {}",
                self.buf[6]
            )));
        }
        Ok(())
    }

    /// Offset from which the next record read will start; usable with
    /// `seek_record` to return to the same position.
    pub fn next_offset(&self) -> i64 {
        self.block_offset + self.next_chunk_start as i64
    }

    /// Reads the next full record payload.
    pub fn next_record(&mut self) -> Result<Vec<u8>, Error> {
        if let Some(kind) = self.failed {
            return Err(kind.into());
        }
        if let Err(e) = self.next_chunk(true) {
            self.failed = Some(classify(&e));
            return Err(e);
        }

        let mut out = Vec::with_capacity(self.j - self.i);
        loop {
            out.extend_from_slice(&self.buf[self.i..self.j]);
            self.i = self.j;
            if self.last {
                return Ok(out);
            }
            if let Err(e) = self.next_chunk(false) {
                // Expected more chunks: map EOF to unexpected EOF.
                let e = if matches!(e, Error::Eof) {
                    Error::UnexpectedEof
                } else {
                    e
                };
                self.failed = Some(classify(&e));
                return Err(e);
            }
        }
    }

    /// Clears errors so `next` will start reading from the next good block.
    pub fn recover(&mut self) {
        if self.failed.is_none() {
            return;
        }
        self.recovering = true;
        self.failed = None;
        self.i = 0;
        self.j = 0;
        self.last = false;
        self.next_chunk_start = self.n;
    }

    /// Seeks so that the next call to `next` reads the record whose first
    /// chunk header starts at `offset`. Clears retryable errors.
    pub fn seek_record(&mut self, offset: i64) -> Result<(), Error> {
        if let Some(kind) = self.failed {
            if kind == ErrorKind::Corrupt {
                return Err(kind.into());
            }
            self.failed = None;
        }

        self.i = 0;
        self.j = 0;
        self.n = 0;
        self.recovering = false;
        self.last = false;

        self.next_chunk_start = (offset & (BLOCK_SIZE as i64 - 1)) as usize;
        self.block_offset = offset & !(BLOCK_SIZE as i64 - 1);
        self.r.seek(SeekFrom::Start(self.block_offset as u64))?;
        Ok(())
    }

    fn next_chunk(&mut self, want_first: bool) -> Result<(), Error> {
        loop {
            if self.next_chunk_start + HEADER_SIZE <= self.n {
                match self.read_chunk_in_block(self.next_chunk_start) {
                    Ok(Ok(chunk_type)) => {
                        if want_first && chunk_type != FULL_CHUNK && chunk_type != FIRST_CHUNK {
                            continue;
                        }
                        return Ok(());
                    }
                    Ok(Err(ZeroChunk)) if self.recovering || want_first => {
                        self.failed = Some(ErrorKind::Corrupt);
                        self.recover();
                        continue;
                    }
                    Ok(Err(ZeroChunk)) => {
                        return Err(Error::Corrupt("block appears to be zeroed".into()));
                    }
                    Err(e) if self.recovering => {
                        self.failed = Some(classify(&e));
                        self.recover();
                        continue;
                    }
                    Err(e) => return Err(e),
                }
            }

            // There must be no bytes after the final chunk. Detectable only
            // when the final block is not full-size.
            if self.is_short_block() && 0 < self.j && self.j != self.n {
                return Err(Error::UnexpectedEof);
            }

            // Next chunk expected in this block but the block ended early.
            if self.next_chunk_start < self.n {
                return Err(Error::UnexpectedEof);
            }

            self.read_block()?;
        }
    }

    /// Returns `Ok(Ok(chunk_type))` on success, `Ok(Err(ZeroChunk))` for a
    /// zeroed header, or `Err` for corruption.
    fn read_chunk_in_block(&mut self, start: usize) -> Result<Result<u8, ZeroChunk>, Error> {
        let checksum = u32::from_le_bytes(self.buf[start..start + 4].try_into().unwrap());
        let length = u16::from_le_bytes(self.buf[start + 4..start + 6].try_into().unwrap());
        let chunk_type = self.buf[start + 6];

        if checksum == 0 && length == 0 && chunk_type == 0 {
            return Ok(Err(ZeroChunk));
        }

        self.i = start + HEADER_SIZE;
        self.j = start + HEADER_SIZE + length as usize;
        self.next_chunk_start = start_of_chunk_after(self.j);

        if self.j > BLOCK_SIZE {
            return Err(Error::Corrupt(format!("chunk too long ({length})")));
        }
        if self.j > self.n {
            return Err(Error::UnexpectedEof);
        }
        if checksum != crc32fast::hash(&self.buf[self.i - 1..self.j]) {
            return Err(Error::Corrupt("invalid chunk (checksum mismatch)".into()));
        }

        self.last = chunk_type == FULL_CHUNK || chunk_type == LAST_CHUNK;
        self.recovering = false;
        let _ = MIDDLE_CHUNK; // part of the wire format; validated implicitly
        Ok(Ok(chunk_type))
    }

    fn read_block(&mut self) -> Result<(), Error> {
        if self.is_short_block() {
            return Err(Error::Eof);
        }

        let prev_block_size = self.n;
        let next_block_offset = self.block_offset + prev_block_size as i64;
        let n = read_full(&mut self.r, &mut self.buf[..])?;
        if n == 0 {
            return Err(Error::Eof);
        }

        self.block_offset = next_block_offset;
        self.i = 0;
        self.j = 0;
        self.n = n;
        self.next_chunk_start = self.next_chunk_start.saturating_sub(prev_block_size);
        Ok(())
    }

    fn is_short_block(&self) -> bool {
        0 < self.n && self.n < BLOCK_SIZE
    }
}

impl From<ErrorKind> for Error {
    fn from(kind: ErrorKind) -> Self {
        match kind {
            ErrorKind::Eof => Error::Eof,
            ErrorKind::UnexpectedEof => Error::UnexpectedEof,
            ErrorKind::Corrupt => Error::Corrupt("previous error".into()),
        }
    }
}

fn classify(e: &Error) -> ErrorKind {
    match e {
        Error::Eof => ErrorKind::Eof,
        Error::UnexpectedEof => ErrorKind::UnexpectedEof,
        _ => ErrorKind::Corrupt,
    }
}

/// The starting offset of the chunk following one that ends at `chunk_end`.
/// If another chunk header wouldn't fit in this block, the next chunk starts
/// in the next block (the remainder is zero padding).
fn start_of_chunk_after(chunk_end: usize) -> usize {
    if chunk_end + HEADER_SIZE <= BLOCK_SIZE {
        chunk_end
    } else {
        BLOCK_SIZE
    }
}

/// Reads as many bytes as possible into `buf`, stopping at EOF.
fn read_full<R: Read>(r: &mut R, buf: &mut [u8]) -> io::Result<usize> {
    let mut n = 0;
    while n < buf.len() {
        match r.read(&mut buf[n..]) {
            Ok(0) => break,
            Ok(m) => n += m,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    /// Minimal writer used to build test fixtures.
    pub fn write_log(records: &[&[u8]]) -> Vec<u8> {
        let mut out = Vec::new();
        out.extend_from_slice(WANDB_IDENT);
        out.extend_from_slice(&WANDB_MAGIC.to_le_bytes());
        out.push(WANDB_STORE_VERSION);

        let mut block_used = WANDB_HEADER_LEN;
        for rec in records {
            let mut remaining = *rec;
            let mut first = true;
            loop {
                if block_used + HEADER_SIZE > BLOCK_SIZE {
                    // Pad to block boundary.
                    out.resize(out.len() + (BLOCK_SIZE - block_used), 0);
                    block_used = 0;
                }
                let avail = BLOCK_SIZE - block_used - HEADER_SIZE;
                let take = remaining.len().min(avail);
                let (chunk, rest) = remaining.split_at(take);
                let last = rest.is_empty();
                let chunk_type = match (first, last) {
                    (true, true) => FULL_CHUNK,
                    (true, false) => FIRST_CHUNK,
                    (false, false) => MIDDLE_CHUNK,
                    (false, true) => LAST_CHUNK,
                };
                let mut hasher = crc32fast::Hasher::new();
                hasher.update(&[chunk_type]);
                hasher.update(chunk);
                out.extend_from_slice(&hasher.finalize().to_le_bytes());
                out.extend_from_slice(&(take as u16).to_le_bytes());
                out.push(chunk_type);
                out.extend_from_slice(chunk);
                block_used += HEADER_SIZE + take;
                remaining = rest;
                first = false;
                if last {
                    break;
                }
            }
        }
        out
    }

    #[test]
    fn round_trip_small_records() {
        let recs: Vec<Vec<u8>> = vec![b"hello".to_vec(), b"world".to_vec(), vec![7u8; 100]];
        let refs: Vec<&[u8]> = recs.iter().map(|r| r.as_slice()).collect();
        let data = write_log(&refs);

        let mut reader = RecordReader::new(Cursor::new(data));
        reader.verify_wandb_header(WANDB_STORE_VERSION).unwrap();
        for rec in &recs {
            assert_eq!(&reader.next_record().unwrap(), rec);
        }
        assert!(matches!(reader.next_record(), Err(Error::Eof)));
    }

    #[test]
    fn round_trip_multi_block_record() {
        let big = vec![42u8; 100_000];
        let data = write_log(&[&big, b"tail"]);

        let mut reader = RecordReader::new(Cursor::new(data));
        reader.verify_wandb_header(WANDB_STORE_VERSION).unwrap();
        assert_eq!(reader.next_record().unwrap(), big);
        assert_eq!(reader.next_record().unwrap(), b"tail");
    }

    #[test]
    fn live_tail_resume_with_seek() {
        let data = write_log(&[b"one"]);
        let mut full = write_log(&[b"one", b"two"]);

        let mut reader = RecordReader::new(Cursor::new(data.clone()));
        reader.verify_wandb_header(WANDB_STORE_VERSION).unwrap();
        assert_eq!(reader.next_record().unwrap(), b"one");
        let offset = reader.next_offset();
        assert!(reader.next_record().unwrap_err().is_retryable());

        // Simulate the file growing, then resume from the recorded offset.
        let mut reader = RecordReader::new(Cursor::new(std::mem::take(&mut full)));
        reader.seek_record(offset).unwrap();
        assert_eq!(reader.next_record().unwrap(), b"two");
    }
}
