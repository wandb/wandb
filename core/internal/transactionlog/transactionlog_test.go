package transactionlog_test

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// emptyWandbFile creates an empty .wandb file with a valid header and returns
// its path.
func emptyWandbFile(t *testing.T) string {
	t.Helper()

	path := filepath.Join(t.TempDir(), "run.wandb")
	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, writer.Close())

	return path
}

func Test_ReadAfterWrite(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")

	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, writer.Write(&spb.Record{Num: 123}))
	require.NoError(t, writer.Close())

	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	record, err := reader.Read()
	require.NoError(t, err)
	reader.Close()

	assert.EqualValues(t, 123, record.Num)
}

func Test_OpenWriter_FileExists(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")
	require.NoError(t, os.WriteFile(path, []byte{}, 0o666))

	writer, err := transactionlog.OpenWriter(path)

	assert.Nil(t, writer)
	assert.ErrorIs(t, err, os.ErrExist)
}

func Test_Write_AlreadyClosed(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")
	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	require.NoError(t, writer.Close())
	err = writer.Write(&spb.Record{})

	assert.ErrorContains(t, err, "writer is closed")
}

func Test_OpenReader_NoFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")

	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))

	assert.Nil(t, reader)
	assert.ErrorIs(t, err, os.ErrNotExist)
}

func Test_OpenReader_BadHeader(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")
	require.NoError(t, os.WriteFile(path, []byte{1, 2, 3, 4, 5, 6, 7}, 0o666))

	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	_, err = reader.Read()
	assert.ErrorContains(t, err, "bad header")
}

func Test_Read_AlreadyClosed(t *testing.T) {
	path := emptyWandbFile(t)
	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	reader.Close()
	record, err := reader.Read()

	assert.Nil(t, record)
	assert.ErrorContains(t, err, "reader is closed")
}

func Test_Read_EOF(t *testing.T) {
	path := emptyWandbFile(t)
	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	record, err := reader.Read()

	assert.Nil(t, record)
	assert.ErrorIs(t, err, io.EOF)
}

func Test_Read_SkipsCorruptData(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")

	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

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
	require.NoError(t, writer.Write(&spb.Record{Num: 13})) // bytes 7..15
	for range 4678 {                                       // bytes 16..32761
		require.NoError(t, writer.Write(&spb.Record{}))
	}
	require.NoError(t, writer.Write(&spb.Record{Num: 31})) // 9 bytes
	require.NoError(t, writer.Close())

	// Now corrupt the second record in the file (starting at byte 16).
	f, err := os.OpenFile(path, os.O_WRONLY, 0)
	require.NoError(t, err)
	_, err = f.WriteAt([]byte{1, 2, 3, 4, 5, 6, 7}, 16)
	require.NoError(t, err)
	require.NoError(t, f.Close())

	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	defer reader.Close()

	record1, err1 := reader.Read()
	_, err2 := reader.Read() // Second record is corrupt, block is skipped.
	record3, err3 := reader.Read()

	assert.NoError(t, err1)
	assert.ErrorContains(t, err2, "error getting next record")
	assert.NoError(t, err3)
	assert.EqualValues(t, 13, record1.GetNum())
	assert.EqualValues(t, 31, record3.GetNum())
}

func Test_ResetLastRead(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")

	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, writer.Write(&spb.Record{Num: 13}))
	require.NoError(t, writer.Write(&spb.Record{Num: 14}))
	require.NoError(t, writer.Write(&spb.Record{Num: 15}))
	require.NoError(t, writer.Close())

	reader, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	defer reader.Close()

	// Test reading, resetting, and reading again after each record.
	for _, num := range []int{13, 14, 15} {
		record, err := reader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, num, record.GetNum())

		require.NoError(t, reader.ResetLastRead())

		record, err = reader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, num, record.GetNum())
	}
}

func Test_EOF(t *testing.T) {
	// Test that EOF and ErrUnexpectedEOF errors are correctly wrapped.

	path := filepath.Join(t.TempDir(), "run.wandb")
	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, writer.Write(&spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Item: []*spb.HistoryItem{
					// Results in a 32 KiB record that requires 2 blocks
					// to store, so that we can test errors from the reader
					// returned by Next().
					{Key: "data", ValueJson: strings.Repeat("a", 32*1024)},
				},
			},
		},
	}))
	require.NoError(t, writer.Close())

	data, err := os.ReadFile(path)
	require.NoError(t, err)

	dataEmpty := io.NewSectionReader(bytes.NewReader(data), 0, 0)
	dataShortHeader := io.NewSectionReader(bytes.NewReader(data), 0, 5)
	dataShortFirstChunk := io.NewSectionReader(bytes.NewReader(data), 0, 20)
	dataNoLastChunk := io.NewSectionReader(bytes.NewReader(data), 0, 32*1024)

	doTest := func(t *testing.T, data io.Reader, expectedErr error) {
		logger := observabilitytest.NewTestLogger(t)
		reader, err := transactionlog.NewReader(io.NopCloser(data), logger)
		require.NoError(t, err)
		defer reader.Close()

		_, err = reader.Read()
		assert.ErrorIs(t, err, expectedErr)
	}

	t.Run("empty is EOF", func(t *testing.T) {
		doTest(t, dataEmpty, io.EOF)
	})

	t.Run("short header is ErrUnexpectedEOF", func(t *testing.T) {
		doTest(t, dataShortHeader, io.ErrUnexpectedEOF)
	})

	t.Run("short first chunk is ErrUnexpectedEOF", func(t *testing.T) {
		doTest(t, dataShortFirstChunk, io.ErrUnexpectedEOF)
	})

	t.Run("missing last chunk is ErrUnexpectedEOF", func(t *testing.T) {
		doTest(t, dataNoLastChunk, io.ErrUnexpectedEOF)
	})
}
