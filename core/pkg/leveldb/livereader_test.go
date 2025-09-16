package leveldb_test

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/wandb/wandb/core/pkg/leveldb"
)

const (
	blockSize         = 32 * 1024
	headerSize        = 7
	wandbHeaderLength = 7
)

// encodeRecords serializes one or more records using the W&B writer with the
// given CRC algorithm and W&B header version.
func encodeRecords(t *testing.T, algo leveldb.CRCAlgo, version byte, recs ...[]byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := leveldb.NewWriterExt(&buf, algo, version)
	for _, r := range recs {
		ww, err := w.Next()
		if err != nil {
			t.Fatalf("writer.Next: %v", err)
		}
		if _, err := ww.Write(r); err != nil {
			t.Fatalf("writer.Write: %v", err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatalf("writer.Close: %v", err)
	}
	return buf.Bytes()
}

func openLiveFiles(t *testing.T) (path string, w *os.File, r *os.File, cleanup func()) {
	t.Helper()
	dir := t.TempDir()
	path = filepath.Join(dir, "live.wandb")
	// Writer handle (append).
	wh, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		t.Fatalf("open writer: %v", err)
	}
	// Reader handle (ReadAt).
	rh, err := os.Open(path)
	if err != nil {
		_ = wh.Close()
		t.Fatalf("open reader: %v", err)
	}
	cleanup = func() {
		_ = wh.Close()
		_ = rh.Close()
	}
	return path, wh, rh, cleanup
}

func appendAndSync(t *testing.T, w *os.File, p []byte) {
	t.Helper()
	if len(p) == 0 {
		return
	}
	if _, err := w.Write(p); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := w.Sync(); err != nil {
		t.Fatalf("sync: %v", err)
	}
}

func readAll(t *testing.T, r io.Reader) []byte {
	t.Helper()
	b, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("readAll: %v", err)
	}
	return b
}

func TestLiveReader_PartialHeaderAndPayload(t *testing.T) {
	// Partial W&B header, then partial chunk header, then partial payload.
	// Next() must return io.EOF until the complete record is available.

	t.Parallel()

	_, w, rf, cleanup := openLiveFiles(t)
	defer cleanup()

	// One small record.
	payload := []byte("hello world")
	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, payload)

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// 0. Empty file -> soft EOF.
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF on empty file, got %v", err)
	}

	// 1. Write partial W&B header (3 bytes).
	appendAndSync(t, w, stream[:3])
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF with partial W&B header, got %v", err)
	}

	// 2. Finish W&B header (bytes 3..6).
	appendAndSync(t, w, stream[3:7])
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF with only W&B header present, got %v", err)
	}

	// 3. Write partial chunk header (7..10).
	appendAndSync(t, w, stream[7:10])
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF with partial chunk header, got %v", err)
	}

	// 4. Finish chunk header (10..14).
	appendAndSync(t, w, stream[10:14])
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF with no payload yet, got %v", err)
	}

	// 5. Write all payload except the last byte.
	appendAndSync(t, w, stream[14:len(stream)-1])
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF with last payload byte missing, got %v", err)
	}

	// 6. Write last byte -> record should be readable now.
	appendAndSync(t, w, stream[len(stream)-1:])
	rdr, err := lr.Next()
	if err != nil {
		t.Fatalf("Next(): %v", err)
	}
	got := readAll(t, rdr)
	if !bytes.Equal(got, payload) {
		t.Fatalf("payload mismatch: got %q want %q", string(got), string(payload))
	}
}

func TestLiveReader_DoesNotSkipGoodRecordWhenNextIsIncomplete(t *testing.T) {
	// Do not skip a good record when the following one is incomplete.
	t.Parallel()

	_, w, rf, cleanup := openLiveFiles(t)
	defer cleanup()

	recA := bytes.Repeat([]byte("A"), 1000)
	recB := bytes.Repeat([]byte("B"), 1000)
	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, recA, recB)

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// Write everything except the very last byte of recB.
	appendAndSync(t, w, stream[:len(stream)-1])

	// Should read recA successfully.
	rdr, err := lr.Next()
	if err != nil {
		t.Fatalf("Next() for recA: %v", err)
	}
	gotA := readAll(t, rdr)
	if !bytes.Equal(gotA, recA) {
		t.Fatalf("recA mismatch: got %d bytes want %d", len(gotA), len(recA))
	}

	// recB is incomplete -> io.EOF (soft).
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF for incomplete recB, got %v", err)
	}

	// Append the final byte; recB should be returned on the next call.
	appendAndSync(t, w, stream[len(stream)-1:])
	rdr, err = lr.Next()
	if err != nil {
		t.Fatalf("Next() for recB after append: %v", err)
	}
	gotB := readAll(t, rdr)
	if !bytes.Equal(gotB, recB) {
		t.Fatalf("recB mismatch: got %d bytes want %d", len(gotB), len(recB))
	}
}

func TestLiveReader_MultiChunkRecord_PartialThenComplete(t *testing.T) {
	// One very large record spanning multiple blocks. With the tail missing,
	// Next() must soft-EOF; after appending the final byte, it must return the record.
	t.Parallel()

	_, w, rf, cleanup := openLiveFiles(t)
	defer cleanup()

	// ~2.5 blocks to guarantee FIRST/MIDDLE/LAST chunking.
	long := bytes.Repeat([]byte{0xAB}, blockSize*2+1000)
	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, long)

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// Write everything except last byte of the whole stream.
	appendAndSync(t, w, stream[:len(stream)-1])

	// No complete record yet -> soft EOF.
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF for incomplete large record, got %v", err)
	}

	// Finish the file.
	appendAndSync(t, w, stream[len(stream)-1:])
	rdr, err := lr.Next()
	if err != nil {
		t.Fatalf("Next() after append: %v", err)
	}
	got := readAll(t, rdr)
	if len(got) != len(long) {
		t.Fatalf("length mismatch: got %d want %d", len(got), len(long))
	}
	if !bytes.Equal(got[:64], long[:64]) || !bytes.Equal(got[len(got)-64:], long[len(long)-64:]) {
		t.Fatalf("content mismatch at edges")
	}
}

func TestLiveReader_SkipBlockTailPaddingToNextBlock(t *testing.T) {
	// Block tail padding. First record leaves <7 bytes in the first block,
	// so the next record starts in the next block. Write exactly one block first,
	// then verify the first record is readable, the next is not, and only becomes
	// readable once the next block is appended.
	t.Parallel()

	_, w, rf, cleanup := openLiveFiles(t)
	defer cleanup()

	// First record leaves 3 bytes at end-of-block:
	// payload L1 = blockSize - W&B header - chunk header - 3.
	L1 := blockSize - wandbHeaderLength - headerSize - 3
	rec1 := bytes.Repeat([]byte("X"), L1)
	rec2 := bytes.Repeat([]byte("Y"), 100)

	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, rec1, rec2)

	// Sanity: we expect the first block to be fully occupied after rec1 (+3 zero bytes).
	if len(stream) < blockSize+headerSize+len(rec2) {
		t.Fatalf("unexpected stream shape; got %d bytes", len(stream))
	}

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// Write exactly one full block.
	appendAndSync(t, w, stream[:blockSize])

	// rec1 should be readable.
	rdr, err := lr.Next()
	if err != nil {
		t.Fatalf("Next() rec1: %v", err)
	}
	got1 := readAll(t, rdr)
	if len(got1) != len(rec1) {
		t.Fatalf("rec1 length mismatch: got %d want %d", len(got1), len(rec1))
	}

	// rec2 lives in the next block -> soft EOF until we append that block.
	if _, err := lr.Next(); err != io.EOF {
		t.Fatalf("expected io.EOF for next-block record, got %v", err)
	}

	// Append the remainder of the stream (starting at the second block).
	appendAndSync(t, w, stream[blockSize:])

	// Now rec2 should be returned.
	rdr, err = lr.Next()
	if err != nil {
		t.Fatalf("Next() rec2 after append: %v", err)
	}
	got2 := readAll(t, rdr)
	if !bytes.Equal(got2, rec2) {
		t.Fatalf("rec2 mismatch: got %d bytes want %d", len(got2), len(rec2))
	}
}
