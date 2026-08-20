//! Transliteration of `core/internal/leet/livestore_test.go` (Go package
//! `leet_test`, hence a black-box integration test). Go case names are kept
//! 1:1 in test fn names.
//!
//! PARITY: Go's `observability.NewNoOpLogger()` /
//! `observabilitytest.NewTestLogger(t)` arguments are dropped — the Rust port
//! logs via `tracing` and takes no logger (see the module docs). Go's
//! `defer ls.Close()` is handled by `Drop` (dropping the LiveStore closes the
//! file).

use std::fs::OpenOptions;
use std::io::Write as _;
use std::thread;
use std::time::{Duration, Instant};

use leet_proto::wandb_internal as spb;
use leet_wire::crc::CrcAlgo;
use leet_wire::live_store::LiveStore;
use leet_wire::record;
use leet_wire::transaction_log::open_writer;
use prost::Message as _;

/// TestNewLiveStore_ValidFile tests creating a LiveStore with a valid file
#[test]
fn test_new_live_store_valid_file() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("valid.wandb");

    // Write a valid header to a tranaction log.
    let mut w = open_writer(&path).unwrap();
    w.close().unwrap();

    // Now open with LiveStore
    let mut ls = LiveStore::new(&path).unwrap();

    // Should be able to read (will get EOF since no records)
    let err = ls.read().unwrap_err();
    // Go: `require.ErrorIs(t, err, io.EOF)`.
    assert!(err.is_eof(), "{err}");
}

/// TestNewLiveStore_NonExistentFile tests error handling for missing files
#[test]
fn test_new_live_store_non_existent_file() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("nonexistent.wandb");
    assert!(LiveStore::new(&path).is_err());
}

/// TestNewLiveStore_InvalidHeader tests handling of files with invalid headers
#[test]
fn test_new_live_store_invalid_header() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("invalid-header.wandb");

    // Write invalid header data
    std::fs::write(&path, "INVALID_HEADER_DATA").unwrap();

    let mut store = LiveStore::new(&path).unwrap();

    let err = store.read().unwrap_err();
    assert!(err.to_string().contains("bad header"), "{err}");
}

/// TestLiveStore_ReadValidRecords tests reading valid records
#[test]
fn test_live_store_read_valid_records() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("records.wandb");

    // Write records using regular Store
    // Write a valid header to a tranaction log.
    let mut w = open_writer(&path).unwrap();

    let records = [
        spb::Record {
            num: 1,
            ..Default::default()
        },
        spb::Record {
            num: 2,
            ..Default::default()
        },
        spb::Record {
            num: 3,
            ..Default::default()
        },
    ];

    for rec in &records {
        w.write(rec).unwrap();
    }
    w.close().unwrap();

    // Read with LiveStore
    let mut ls = LiveStore::new(&path).unwrap();

    // Read all records
    for expected in &records {
        let rec = ls.read().unwrap();
        assert_eq!(rec.num, expected.num);
    }

    // Next read should return EOF
    let err = ls.read().unwrap_err();
    assert!(err.is_eof(), "{err}");
}

/// TestLiveStore_ReadAfterClose tests that reading after close returns an error
#[test]
fn test_live_store_read_after_close() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("read-after-close.wandb");

    // Create valid file with a record.
    let mut w = open_writer(&path).unwrap();
    let _ = w.write(&spb::Record {
        num: 1,
        ..Default::default()
    });
    w.close().unwrap();

    let mut ls = LiveStore::new(&path).unwrap();

    // Close the LiveStore.
    ls.close();

    // Try to read after close.
    let err = ls.read().unwrap_err();
    assert_eq!(err.to_string(), "livestore: reader is closed");
}

/// TestLiveStore_LiveRead_ConcurrentWriterFlushes writes records in one thread
/// using the low-level LevelDB writer (so we can Flush) and reads them from
/// another. It ensures we see newly flushed records in order, and only get
/// io.EOF between flushes.
#[test]
fn test_live_store_live_read_concurrent_writer_flushes() {
    let tmp = tempfile::tempdir().unwrap();
    // Go: `os.CreateTemp(t.TempDir(), "live-*.wandb")` creates the (empty)
    // file before the reader opens it.
    let path = tmp.path().join("live.wandb");
    std::fs::write(&path, []).unwrap();

    const TOTAL: i64 = 50;

    // Writer goroutine.
    let writer_path = path.clone();
    let writer = thread::spawn(move || {
        let f = OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&writer_path)
            .expect("open for write");

        // Match LiveStore (CRCAlgoIEEE, version 0).
        //
        // Go: `leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, 0)` — Go detects
        // that *os.File is an io.Seeker; new_ext_seekable matches.
        let mut w = record::Writer::new_ext_seekable(f, CrcAlgo::Ieee, 0);

        for i in 0..TOTAL {
            let rec = spb::Record {
                num: i,
                ..Default::default()
            };
            let payload = rec.encode_to_vec();

            let chunk = w.next().expect("writer.Next");
            chunk.write(&mut w, &payload).expect("writer.Write");
            w.flush().expect("writer.Flush");

            // Small delay to exercise reader's EOF path between records.
            thread::sleep(Duration::from_millis(2));
        }
        // Finish cleanly.
        w.close().expect("writer.Close");
    });

    // Reader on the same file.
    let mut ls = LiveStore::new(&path).unwrap();

    let deadline = Instant::now() + Duration::from_secs(5);
    let mut i: i64 = 0;
    while i < TOTAL {
        assert!(
            Instant::now() < deadline,
            "timeout waiting for record {i}/{TOTAL}"
        );
        match ls.read() {
            // Go: `errors.Is(err, io.EOF)`.
            Err(err) if err.is_eof() => {
                // No complete record yet; try again shortly.
                thread::sleep(Duration::from_millis(1));
            }
            Err(err) => panic!("{err}"),
            Ok(rec) => {
                assert_eq!(rec.num, i);
                i += 1;
            }
        }
    }
    writer.join().unwrap();
}

#[test]
fn test_live_store_live_read_opened_before_writer() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("live.wandb");
    std::fs::write(&path, []).unwrap();

    // Start reader first: header may not exist yet; allowed by NewLiveStore.
    let mut ls = LiveStore::new(&path).unwrap();

    // Now start the writer.
    let writer_path = path.clone();
    let writer = thread::spawn(move || {
        let f = OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&writer_path)
            .expect("open for write");
        let mut w = record::Writer::new_ext_seekable(f, CrcAlgo::Ieee, 0);

        let rec = spb::Record {
            num: 1,
            ..Default::default()
        };
        let payload = rec.encode_to_vec();
        let chunk = w.next().expect("writer.Next");
        chunk.write(&mut w, &payload).expect("writer.Write");
        w.flush().expect("writer.Flush");
        let _ = w.close();
    });

    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        assert!(
            Instant::now() < deadline,
            "timeout waiting for first record"
        );
        match ls.read() {
            Err(err) if err.is_eof() => {
                thread::sleep(Duration::from_millis(1));
            }
            Err(err) => panic!("{err}"),
            Ok(rec) => {
                assert_eq!(rec.num, 1);
                writer.join().unwrap();
                return;
            }
        }
    }
}

/// test_live_store_tail_resume_record_appended_in_two_flushes is a
/// harness-mandated tail-resume test (Phase 1 differential; not a
/// transliteration of a Go case — Go's liveread_test.go exercises the
/// HistorySource layer above LiveStore, see the note in `src/live_store.rs`).
///
/// A single record's bytes land in the file across two appends by the ported
/// Writer: the record spans two LevelDB blocks, so writing its payload spills
/// the full first block to disk mid-record, and `flush` later appends the
/// last chunk. A polling Reader must classify the half-written record as EOF
/// (Go maps the record layer's io.ErrUnexpectedEOF to io.EOF for live
/// reading), rewind via ResetLastRead, and deliver the whole record once the
/// second flush lands.
#[test]
fn test_live_store_tail_resume_record_appended_in_two_flushes() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("tail-resume.wandb");

    let f = std::fs::File::create(&path).unwrap();
    let mut w = record::Writer::new_ext_seekable(f, CrcAlgo::Ieee, 0);

    // Flush #1: the W&B header reaches the file (like OpenWriter does).
    w.flush().expect("writer.Flush");

    // The reader polls a file with a header but no records: clean EOF.
    let mut ls = LiveStore::new(&path).unwrap();
    let err = ls.read().unwrap_err();
    assert!(err.is_eof(), "{err}");

    // A record big enough to span two blocks: the first chunk fills the rest
    // of block 0 (32 KiB - 7 B header - 7 B chunk header = 32754 payload
    // bytes), the last chunk lands in block 1.
    let rec = spb::Record {
        num: 42,
        record_type: Some(spb::record::RecordType::OutputRaw(spb::OutputRawRecord {
            line: "x".repeat(40_000),
            ..Default::default()
        })),
        ..Default::default()
    };
    let payload = rec.encode_to_vec();
    assert!(payload.len() > 32 * 1024, "record must span two blocks");

    // Append #1: writing the payload spills the completed first block (with
    // a FIRST-type chunk) to the file; the record is not finished.
    let chunk = w.next().expect("writer.Next");
    chunk.write(&mut w, &payload).expect("writer.Write");

    // The reader sees a valid first chunk but no last chunk: the record
    // layer reports unexpected EOF, which LiveStore treats the same as a
    // regular EOF for live reading (and rewinds to retry the same record).
    let err = ls.read().unwrap_err();
    assert!(err.is_eof(), "half-written record must read as EOF: {err}");

    // Flush #2: the record's LAST chunk reaches the file.
    w.flush().expect("writer.Flush");

    // The next poll resumes from the record's offset and gets all of it.
    let got = ls.read().expect("record after second flush");
    assert_eq!(got.num, 42);
    match got.record_type {
        Some(spb::record::RecordType::OutputRaw(ref raw)) => {
            assert_eq!(raw.line.len(), 40_000);
            assert_eq!(raw.line, "x".repeat(40_000));
        }
        ref other => panic!("wrong record_type: {other:?}"),
    }

    // And the stream is cleanly at EOF again.
    let err = ls.read().unwrap_err();
    assert!(err.is_eof(), "{err}");

    w.close().expect("writer.Close");
}

/// TestLiveStore_LargeRecord tests handling of large records
#[test]
fn test_live_store_large_record() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("large.wandb");

    let mut w = open_writer(&path).unwrap();

    // Create a large record
    //
    // PARITY: the Go test builds this 1MB buffer but never attaches it to
    // the record; transliterated verbatim.
    let mut large_data = vec![0u8; 1024 * 1024]; // 1MB
    for (i, b) in large_data.iter_mut().enumerate() {
        *b = (i % 256) as u8;
    }

    let large_record = spb::Record {
        num: 1,
        ..Default::default()
    };

    w.write(&large_record).unwrap();
    w.close().unwrap();

    // Read with LiveStore
    let mut ls = LiveStore::new(&path).unwrap();

    let rec = ls.read().unwrap();
    assert_eq!(rec.num, large_record.num);
}

/// TestLiveStore_PartialWrite tests handling of partial writes
#[test]
fn test_live_store_partial_write() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("partial.wandb");

    // Write header
    let mut w = open_writer(&path).unwrap();

    // Write one complete record
    w.write(&spb::Record {
        num: 1,
        ..Default::default()
    })
    .unwrap();
    w.close().unwrap();

    // Append partial record data (simulate interrupted write)
    let mut f = OpenOptions::new().append(true).open(&path).unwrap();
    // Write incomplete record header
    let _ = f.write_all(&[0x00, 0x00]); // Partial record that will cause read error
    drop(f);

    // Try to read
    let mut ls = LiveStore::new(&path).unwrap();

    // First record should be readable
    let rec = ls.read().unwrap();
    assert_eq!(rec.num, 1);

    // Second read should fail or return EOF
    assert!(ls.read().is_err());
}
