//! Transliteration of `core/internal/transactionlog/transactionlog_test.go`
//! (Go package `transactionlog_test`, hence a black-box integration test).
//! Go case names are kept 1:1 in test fn names and sub-case strings.
//!
//! PARITY: Go's `observabilitytest.NewTestLogger(t)` arguments are dropped —
//! the Rust port logs via `tracing` and takes no logger (see the module docs).

use std::io::{self, Cursor, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use leet_proto::wandb_internal as spb;
use leet_wire::record::RecordError;
use leet_wire::transaction_log::{new_reader, open_reader, open_writer};

/// emptyWandbFile creates an empty .wandb file with a valid header and returns
/// its path.
fn empty_wandb_file(dir: &Path) -> PathBuf {
    let path = dir.join("run.wandb");
    let mut writer = open_writer(&path).unwrap();
    writer.close().unwrap();

    path
}

#[test]
fn test_read_after_write() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");

    let mut writer = open_writer(&path).unwrap();
    writer
        .write(&spb::Record {
            num: 123,
            ..Default::default()
        })
        .unwrap();
    writer.close().unwrap();

    let mut reader = open_reader(&path).unwrap();
    let record = reader.read().unwrap();
    reader.close();

    assert_eq!(record.num, 123);
}

#[test]
fn test_open_writer_file_exists() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");
    std::fs::write(&path, []).unwrap();

    let err = open_writer(&path).unwrap_err();

    // Go: `assert.ErrorIs(t, err, os.ErrExist)`.
    assert_eq!(
        err.io_error().expect("expected a wrapped os error").kind(),
        io::ErrorKind::AlreadyExists,
        "{err}"
    );
}

#[test]
fn test_write_already_closed() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");
    let mut writer = open_writer(&path).unwrap();

    writer.close().unwrap();
    let err = writer.write(&spb::Record::default()).unwrap_err();

    assert!(err.to_string().contains("writer is closed"), "{err}");
}

#[test]
fn test_open_reader_no_file() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");

    let err = open_reader(&path).unwrap_err();

    // Go: `assert.ErrorIs(t, err, os.ErrNotExist)`.
    assert_eq!(
        err.io_error().expect("expected a wrapped os error").kind(),
        io::ErrorKind::NotFound,
        "{err}"
    );
}

#[test]
fn test_open_reader_bad_header() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");
    std::fs::write(&path, [1, 2, 3, 4, 5, 6, 7]).unwrap();

    let mut reader = open_reader(&path).unwrap();

    let err = reader.read().unwrap_err();
    assert!(err.to_string().contains("bad header"), "{err}");
}

#[test]
fn test_read_already_closed() {
    let tmp = tempfile::tempdir().unwrap();
    let path = empty_wandb_file(tmp.path());
    let mut reader = open_reader(&path).unwrap();

    reader.close();
    let err = reader.read().unwrap_err();

    assert!(err.to_string().contains("reader is closed"), "{err}");
}

#[test]
fn test_read_eof() {
    let tmp = tempfile::tempdir().unwrap();
    let path = empty_wandb_file(tmp.path());
    let mut reader = open_reader(&path).unwrap();

    let err = reader.read().unwrap_err();

    // Go: `assert.ErrorIs(t, err, io.EOF)`.
    assert!(err.is_eof(), "{err}");
}

#[test]
fn test_read_skips_corrupt_data() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");

    let mut writer = open_writer(&path).unwrap();

    // The first 7 bytes of the first block are the W&B header.
    //
    // A record with just Num set to a small number is encoded as 2 bytes.
    // An empty record is encoded as 0 bytes.
    // An additional 7 bytes per record are used for the leveldb header.
    // The block size is 32KiB.
    //
    // So after one 9-byte record and 4678 7-byte records, the next record
    // goes into the second block.
    //
    // This is stable because the leveldb and protobuf formats are stable.
    writer
        .write(&spb::Record {
            num: 13,
            ..Default::default()
        })
        .unwrap(); // bytes 7..15
    for _ in 0..4678 {
        // bytes 16..32761
        writer.write(&spb::Record::default()).unwrap();
    }
    writer
        .write(&spb::Record {
            num: 31,
            ..Default::default()
        })
        .unwrap(); // 9 bytes
    writer.close().unwrap();

    // Now corrupt the second record in the file (starting at byte 16).
    let mut f = std::fs::OpenOptions::new().write(true).open(&path).unwrap();
    f.seek(SeekFrom::Start(16)).unwrap(); // Go: f.WriteAt(..., 16)
    f.write_all(&[1, 2, 3, 4, 5, 6, 7]).unwrap();
    drop(f);

    let mut reader = open_reader(&path).unwrap();

    let result1 = reader.read();
    let result2 = reader.read(); // Second record is corrupt, block is skipped.
    let result3 = reader.read();
    reader.close();

    let record1 = result1.expect("read #1");
    let err2 = result2.expect_err("read #2 should fail");
    let record3 = result3.expect("read #3");
    assert!(
        err2.to_string().contains("error getting next record"),
        "{err2}"
    );
    assert_eq!(record1.num, 13);
    assert_eq!(record3.num, 31);
}

#[test]
fn test_reset_last_read() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");

    let mut writer = open_writer(&path).unwrap();
    writer
        .write(&spb::Record {
            num: 13,
            ..Default::default()
        })
        .unwrap();
    writer
        .write(&spb::Record {
            num: 14,
            ..Default::default()
        })
        .unwrap();
    writer
        .write(&spb::Record {
            num: 15,
            ..Default::default()
        })
        .unwrap();
    writer.close().unwrap();

    let mut reader = open_reader(&path).unwrap();

    // Test reading, resetting, and reading again after each record.
    for num in [13, 14, 15] {
        let record = reader.read().unwrap();
        assert_eq!(record.num, num);

        reader.reset_last_read().unwrap();

        let record = reader.read().unwrap();
        assert_eq!(record.num, num);
    }
    reader.close();
}

#[test]
fn test_eof() {
    // Test that EOF and ErrUnexpectedEOF errors are correctly wrapped.

    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");
    let mut writer = open_writer(&path).unwrap();
    writer
        .write(&spb::Record {
            record_type: Some(spb::record::RecordType::History(spb::HistoryRecord {
                item: vec![spb::HistoryItem {
                    // Results in a 32 KiB record that requires 2 blocks
                    // to store, so that we can test errors from the reader
                    // returned by Next().
                    key: "data".to_string(),
                    value_json: "a".repeat(32 * 1024),
                    ..Default::default()
                }],
                ..Default::default()
            })),
            ..Default::default()
        })
        .unwrap();
    writer.close().unwrap();

    let data = std::fs::read(&path).unwrap();

    // Go: `io.NewSectionReader(bytes.NewReader(data), 0, N)` wrapped in
    // `io.NopCloser` — a plain non-file byte source.
    fn do_test(name: &str, data: &[u8], expected_err: &RecordError) {
        let mut reader = new_reader(Cursor::new(data)).unwrap();

        let err = reader.read().unwrap_err();
        // Go: `assert.ErrorIs(t, err, expectedErr)`.
        assert_eq!(err.record_error(), Some(expected_err), "{name}: {err}");
        reader.close();
    }

    do_test("empty is EOF", &data[..0], &RecordError::Eof);
    do_test(
        "short header is ErrUnexpectedEOF",
        &data[..5],
        &RecordError::UnexpectedEof,
    );
    do_test(
        "short first chunk is ErrUnexpectedEOF",
        &data[..20],
        &RecordError::UnexpectedEof,
    );
    do_test(
        "missing last chunk is ErrUnexpectedEOF",
        &data[..32 * 1024],
        &RecordError::UnexpectedEof,
    );
}

#[test]
fn test_read_verifies_header() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");
    std::fs::write(&path, b"invalid header").unwrap();

    let mut reader = open_reader(&path).unwrap();
    let err = reader.read().unwrap_err();
    reader.close();

    assert!(err.to_string().contains("invalid W&B identifier"), "{err}");
}

#[test]
fn test_read_after_seek_skips_verifying_header() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("run.wandb");

    // Write an invalid 32KiB block followed by a valid empty chunk.
    // The first 32KiB should be ignored after seeking past them.
    let mut data = vec![0u8; 32 * 1024 + 7];
    for (i, b) in data.iter_mut().take(32 * 1024).enumerate() {
        *b = (i % 256) as u8;
    }
    data[32 * 1024] = 0x1b; // checksum for zero-length chunk
    data[32 * 1024 + 1] = 0xdf;
    data[32 * 1024 + 2] = 0x05;
    data[32 * 1024 + 3] = 0xa5;
    data[32 * 1024 + 4] = 0; // chunk length 0
    data[32 * 1024 + 5] = 0;
    data[32 * 1024 + 6] = 1; // full chunk
    std::fs::write(&path, &data).unwrap();

    let mut reader = open_reader(&path).unwrap();
    reader.seek_record(32 * 1024).unwrap();
    let record = reader.read().unwrap();
    reader.close();

    // Go: `assert.EqualExportedValues(t, &spb.Record{}, record)`.
    assert_eq!(record, spb::Record::default());
}
