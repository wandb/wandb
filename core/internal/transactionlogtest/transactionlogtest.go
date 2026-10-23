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

	w, path := NewWriter(t, &WriterOptions{Records: records})
	require.NoError(t, w.Close())
	return path
}

func WandbFileUnsupportedVersion(t *testing.T, version byte, records ...*spb.Record) string {
	t.Helper()

	w, path := NewWriter(t, &WriterOptions{
		Records:                 records,
		Version:                 version,
		AllowUnsupportedVersion: true,
	})
	require.NoError(t, w.Close())
	return path
}

func WandbFileVersion(t *testing.T, version byte, records ...*spb.Record) string {
	t.Helper()

	w, path := NewWriter(t, &WriterOptions{Records: records, Version: version})
	require.NoError(t, w.Close())
	return path
}

type WriterOptions struct {
	Version                 uint8
	Records                 []*spb.Record
	ParentDir               string
	FileName                string
	AllowUnsupportedVersion bool
}

func NewWriter(t *testing.T, options *WriterOptions) (*transactionlog.Writer, string) {
	t.Helper()
	if options.ParentDir == "" {
		options.ParentDir = t.TempDir()
	}
	if options.FileName == "" {
		options.FileName = "wandb-file.wandb"
	}
	path := filepath.Join(options.ParentDir, options.FileName)

	var w *transactionlog.Writer
	var err error
	if options.AllowUnsupportedVersion {
		w, err = transactionlog.OpenWriter(path)
		require.NoError(t, err)
		writeVersion(t, path, options.Version)
	} else {
		w, err = transactionlog.OpenWriter(path)
		require.NoError(t, err)
	}
	for _, record := range options.Records {
		require.NoError(t, w.Write(record))
	}
	return w, path
}

func writeVersion(t *testing.T, path string, version byte) {
	t.Helper()
	f, err := os.OpenFile(path, os.O_RDWR, 0o600)
	require.NoError(t, err)
	defer f.Close()
	_, err = f.WriteAt([]byte{version}, 6)
	require.NoError(t, err)
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
