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

func WandbFile(t *testing.T, records ...*spb.Record) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "wandb-file.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for _, record := range records {
		require.NoError(t, w.Write(record))
	}
	require.NoError(t, w.Close())

	return path
}

func WandbFileUnsupportedVersion(t *testing.T, version byte, records ...*spb.Record) string {
	t.Helper()

	path := WandbFile(t, records...)
	contents, err := os.ReadFile(path)
	require.NoError(t, err)
	contents[6] = version
	require.NoError(t, os.WriteFile(path, contents, 0o600))
	return path
}

func WandbFileVersion(t *testing.T, version byte, records ...*spb.Record) string {
	t.Helper()
	require.Equal(t, uint8(0), version)
	return WandbFileUnsupportedVersion(t, version, records...)
}

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

	content := validWandbFileContents(t, 0, records...)
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

	content := validWandbFileContents(t, 0)

	r, err := transactionlog.NewReader(
		&readSeekCloser{
			content,
			&errSeeker{},
			&nopCloser{},
		}, observabilitytest.NewTestLogger(t))
	require.NoError(t, err)

	return r
}

// ErrorReader is a reader for which Read always returns a given error.
func ErrorReader(t *testing.T) *transactionlog.Reader {
	t.Helper()

	content := validWandbFileContents(t, 0)
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

// validWandbFileContents contains a valid .wandb file with the given records,
// including at a minimum a 7-byte W&B header.
func validWandbFileContents(t *testing.T, version byte, records ...*spb.Record) *bytes.Buffer {
	t.Helper()
	path := WandbFileVersion(t, version, records...)

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
