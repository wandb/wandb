package runconsolelogs_test

import (
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
)

func TestWritesStructuredFormat(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		fileStream := filestreamtest.NewFakeFileStream()
		w := NewFileStreamWriter(true, fileStream)

		line1 := RunLogsLineForTest("content 1")
		line1Str, err := line1.StructuredFormat()
		require.NoError(t, err)

		line2 := RunLogsLineForTest("content 2")
		line2Str, err := line2.StructuredFormat()
		require.NoError(t, err)

		w.UpdateLine(1, line1)
		w.UpdateLine(2, line2)
		w.Finish()

		updates := fileStream.GetUpdates()
		require.Len(t, updates, 1) // Updates combined by debouncing.
		update, ok := updates[0].(*filestream.LogsUpdate)
		require.True(t, ok)
		assert.Equal(t, line1Str, update.Lines.GetOrZero(1))
		assert.Equal(t, line2Str, update.Lines.GetOrZero(2))
	})
}

func TestWritesLegacyFormat(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		fileStream := filestreamtest.NewFakeFileStream()
		w := NewFileStreamWriter(false, fileStream)

		line1 := RunLogsLineForTest("content 1")
		line1Str := line1.LegacyFormat()

		line2 := RunLogsLineForTest("content 2")
		line2Str := line2.LegacyFormat()

		w.UpdateLine(1, line1)
		w.UpdateLine(2, line2)
		w.Finish()

		updates := fileStream.GetUpdates()
		require.Len(t, updates, 1) // Updates combined by debouncing.
		update, ok := updates[0].(*filestream.LogsUpdate)
		require.True(t, ok)
		assert.Equal(t, line1Str, update.Lines.GetOrZero(1))
		assert.Equal(t, line2Str, update.Lines.GetOrZero(2))
	})
}
