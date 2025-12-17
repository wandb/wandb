package transactionlog_test

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
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

	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)
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

	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)

	assert.Nil(t, reader)
	assert.ErrorIs(t, err, os.ErrNotExist)
}

func Test_OpenReader_BadHeader(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")
	require.NoError(t, os.WriteFile(path, []byte{}, 0o666))

	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)

	assert.Nil(t, reader)
	assert.ErrorContains(t, err, "bad header")
}

func Test_Read_AlreadyClosed(t *testing.T) {
	path := emptyWandbFile(t)
	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)
	require.NoError(t, err)

	reader.Close()
	record, err := reader.Read()

	assert.Nil(t, record)
	assert.ErrorContains(t, err, "reader is closed")
}

func Test_Read_EOF(t *testing.T) {
	path := emptyWandbFile(t)
	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)
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

	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)
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

	reader, err := transactionlog.OpenReader(
		path,
		observabilitytest.NewTestLogger(t),
		true,
	)
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

func Test_Live_ResetLastRead_NoIO(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run.wandb")

	// A record that takes up around 1.25 blocks in the transaction log file.
	//
	// This helps test that cutoff logic correctly uses the block offset.
	makeBigRecord := func(num int64) *spb.Record {
		return &spb.Record{
			Num: num,
			RecordType: &spb.Record_History{
				History: &spb.HistoryRecord{
					Item: []*spb.HistoryItem{
						{
							Key:       "x",
							ValueJson: strings.Repeat("abcdefgh", 4*1024*1.25),
						},
					},
				},
			},
		}
	}

	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for i := range 4 {
		require.NoError(t, writer.Write(makeBigRecord(int64(i))))
	}
	require.NoError(t, writer.Close())

	// Open the file manually to wrap in a reader that intercepts IO.
	file, err := os.Open(path)
	require.NoError(t, err)
	defer file.Close()

	fileIO := transactionlogtest.NewToggleableReadSeeker(file)
	reader, err := transactionlog.NewReader(
		fileIO,
		observabilitytest.NewTestLogger(t),
		true,
	)
	require.NoError(t, err)

	// For all but the last records, there should be no IO when rereading.
	for i := range 4 {
		// Allow IO, so that we may read one record.
		fileIO.SetError(nil)

		rec, err := reader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, i, rec.GetNum())

		// Now turn off IO and attempt rereading.
		if i < 3 {
			// For all but the last record, there will be no seeking or reading.
			fileIO.SetError(errors.New("unexpected IO"))
		} else {
			// For the last record, a single read will be attempted to
			// check if the final block got more data. However, no seeking
			// should occur.
			fileIO.SetSeekError(errors.New("unexpected seek"))
		}

		require.NoError(t, reader.ResetLastRead())
		rec, err = reader.Read()
		require.NoError(t, err)
		assert.EqualValues(t, i, rec.GetNum())
	}
}
