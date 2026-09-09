package runreader_test

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
)

func TestCursor_SkipsCorruptDataAndReportsClose(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	writeLog(t, path, runRecord("abc", nil), historyRecord(1, map[string]string{"loss": "1"}))
	logger := observability.NewNoOpLogger()

	cursor, err := runreader.OpenCursor(path, logger)
	require.NoError(t, err)
	_, _, err = cursor.Next()
	require.NoError(t, err)
	_, offset, err := cursor.Next()
	require.NoError(t, err)
	cursor.Close()

	// Corrupt the second record's checksum; the reader skips the rest of
	// the block, which is the rest of this file.
	data, err := os.ReadFile(path)
	require.NoError(t, err)
	data[offset]++
	require.NoError(t, os.WriteFile(path, data, 0o644))

	cursor, err = runreader.OpenCursor(path, logger)
	require.NoError(t, err)
	record, _, err := cursor.Next()
	require.NoError(t, err)
	assert.Equal(t, "abc", record.GetRun().GetRunId())
	_, _, err = cursor.Next()
	assert.True(t, errors.Is(err, io.EOF), "got %v", err)
	assert.Equal(t, 1, cursor.Skipped())

	cursor.Close()
	_, _, err = cursor.Next()
	assert.ErrorIs(t, err, runreader.ErrClosed)
	assert.Zero(t, cursor.Offset())
}
