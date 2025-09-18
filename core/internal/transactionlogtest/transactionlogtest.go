// Package transactionlogtest provides utilities for testing transaction logs.
package transactionlogtest

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ReaderWriter returns a reader and writer pair connected to the same file.
func ReaderWriter(t *testing.T) (
	*transactionlog.Reader,
	*transactionlog.Writer,
) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "just-the-header.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	r, err := transactionlog.OpenReader(path, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	return r, w
}

// RecordsReader is a reader that produces the given records.
func RecordsReader(
	t *testing.T,
	records ...*spb.Record,
) *transactionlog.Reader {
	t.Helper()

	content := validWandbFile(t, records...)
	contentReader := bytes.NewReader(content.Bytes())

	r, err := transactionlog.NewReader(
		&readSeekCloser{
			contentReader, // read
			contentReader, // seek
			&nopCloser{},
		}, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	return r
}

// UnseekableReader is a reader for which SeekRecord returns an error
// and Read returns EOF.
func UnseekableReader(t *testing.T) *transactionlog.Reader {
	t.Helper()

	content := validWandbFile(t)

	r, err := transactionlog.NewReader(
		&readSeekCloser{
			content,
			&errSeeker{},
			&nopCloser{},
		}, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	return r
}

// RecordThenErrorReader is a reader for which Read() first returns the given
// record, and then returns an error.
//
// Since leveldb's SeekRecord() method reads and validates the first chunk
// in a block, this is the only way to make Read() return an error without
// also making SeekRecord() return an error.
func RecordThenErrorReader(
	t *testing.T,
	record *spb.Record,
) *transactionlog.Reader {
	t.Helper()

	content := validWandbFile(t, record)
	addInvalidChunk(content)
	contentReader := bytes.NewReader(content.Bytes())

	r, err := transactionlog.NewReader(
		&readSeekCloser{
			contentReader, // read
			contentReader, // seek
			&nopCloser{},
		},
		observabilitytest.NewTestLogger(t),
	)
	require.NoError(t, err)

	return r
}

// validWandbFile contains a valid .wandb file with the given records,
// including at a minimum a 7-byte W&B header.
func validWandbFile(t *testing.T, records ...*spb.Record) *bytes.Buffer {
	t.Helper()
	path := filepath.Join(t.TempDir(), "just-the-header.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for _, record := range records {
		require.NoError(t, w.Write(record))
	}
	require.NoError(t, w.Close())

	contents, err := os.ReadFile(path)
	require.NoError(t, err)

	return bytes.NewBuffer(contents)
}

// addInvalidChunk writes an invalid leveldb chunk to the buffer.
func addInvalidChunk(buf *bytes.Buffer) {
	buf.Write([]byte{1, 2, 3, 4}) // Checksum which won't match the content
	buf.Write([]byte{1, 0})       // Content length: 1 (little-endian)
	buf.Write([]byte{1})          // This is a full chunk
	buf.Write([]byte{0})          // Chunk content
}
