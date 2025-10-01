package leveldb_test

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
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
		require.NoError(t, err)
		_, err = ww.Write(r)
		require.NoError(t, err)
	}
	err := w.Close()
	require.NoError(t, err)
	return buf.Bytes()
}

func openLiveFiles(t *testing.T) (path string, w *os.File, r *os.File) {
	t.Helper()
	dir := t.TempDir()
	path = filepath.Join(dir, "live.wandb")
	// Writer handle (append).
	wh, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	require.NoError(t, err)
	// Reader handle (ReadAt).
	rh, err := os.Open(path)
	require.NoError(t, err)
	t.Cleanup(func() {
		_ = wh.Close()
		_ = rh.Close()
	})
	return path, wh, rh
}

func appendAndSync(t *testing.T, w *os.File, p []byte) {
	t.Helper()
	if len(p) == 0 {
		return
	}
	_, err := w.Write(p)
	require.NoError(t, err)

	err = w.Sync()
	require.NoError(t, err)
}

func readAll(t *testing.T, r io.Reader) []byte {
	t.Helper()
	b, err := io.ReadAll(r)
	require.NoError(t, err)
	return b
}

func TestLiveReader_PartialHeaderAndPayload(t *testing.T) {
	// Partial W&B header, then partial chunk header, then partial payload.
	// Next() must return io.EOF until the complete record is available.

	_, w, rf := openLiveFiles(t)

	// One small record.
	payload := []byte("hello world")
	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, payload)

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// 0. Empty file -> soft EOF.
	_, err := lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// 1. Write partial W&B header (3 bytes).
	appendAndSync(t, w, stream[:3])
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// 2. Finish W&B header (bytes 3..6).
	appendAndSync(t, w, stream[3:7])
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// 3. Write partial chunk header (7..10).
	appendAndSync(t, w, stream[7:10])
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// 4. Finish chunk header (10..14).
	appendAndSync(t, w, stream[10:14])
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// 5. Write all payload except the last byte.
	appendAndSync(t, w, stream[14:len(stream)-1])
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// 6. Write last byte -> record should be readable now.
	appendAndSync(t, w, stream[len(stream)-1:])
	rdr, err := lr.Next()
	require.NoError(t, err)
	got := readAll(t, rdr)
	require.Equal(t, got, payload)
}

func TestLiveReader_DoesNotSkipGoodRecordWhenNextIsIncomplete(t *testing.T) {
	// Do not skip a good record when the following one is incomplete.
	_, w, rf := openLiveFiles(t)

	recA := bytes.Repeat([]byte("A"), 1000)
	recB := bytes.Repeat([]byte("B"), 1000)
	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, recA, recB)

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// Write everything except the very last byte of recB.
	appendAndSync(t, w, stream[:len(stream)-1])

	// Should read recA successfully.
	rdr, err := lr.Next()
	require.NoError(t, err)
	gotA := readAll(t, rdr)
	require.Equal(t, recA, gotA)

	// recB is incomplete -> io.EOF (soft).
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// Append the final byte; recB should be returned on the next call.
	appendAndSync(t, w, stream[len(stream)-1:])
	rdr, err = lr.Next()
	require.NoError(t, err)
	gotB := readAll(t, rdr)
	require.Equal(t, recB, gotB)
}

func TestLiveReader_MultiChunkRecord_PartialThenComplete(t *testing.T) {
	// One very large record spanning multiple blocks. With the tail missing,
	// Next() must soft-EOF; after appending the final byte, it must return the record.

	_, w, rf := openLiveFiles(t)

	// ~2.5 blocks to guarantee FIRST/MIDDLE/LAST chunking.
	long := bytes.Repeat([]byte{0xAB}, blockSize*2+1000)
	stream := encodeRecords(t, leveldb.CRCAlgoCustom, 0, long)

	lr := leveldb.NewLiveReader(rf, leveldb.CRCAlgoCustom)

	// Write everything except last byte of the whole stream.
	appendAndSync(t, w, stream[:len(stream)-1])

	// No complete record yet -> soft EOF.
	_, err := lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// Finish the file.
	appendAndSync(t, w, stream[len(stream)-1:])
	rdr, err := lr.Next()
	require.NoError(t, err)
	got := readAll(t, rdr)
	require.Equal(t, len(got), len(long))
	require.Equal(t, got[:64], long[:64])
	require.Equal(t, got[len(got)-64:], long[len(long)-64:])
}

func TestLiveReader_SkipBlockTailPaddingToNextBlock(t *testing.T) {
	// Block tail padding. First record leaves <7 bytes in the first block,
	// so the next record starts in the next block. Write exactly one block first,
	// then verify the first record is readable, the next is not, and only becomes
	// readable once the next block is appended.

	_, w, rf := openLiveFiles(t)

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
	require.NoError(t, err)
	got1 := readAll(t, rdr)
	require.Equal(t, len(got1), len(rec1))

	// rec2 lives in the next block -> soft EOF until we append that block.
	_, err = lr.Next()
	require.ErrorIs(t, err, io.EOF)

	// Append the remainder of the stream (starting at the second block).
	appendAndSync(t, w, stream[blockSize:])

	// Now rec2 should be returned.
	rdr, err = lr.Next()
	require.NoError(t, err)
	got2 := readAll(t, rdr)
	require.Equal(t, rec2, got2)
}
