package runconsolelogs_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filestreamtest"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/settings"
)

func TestWritesStructuredFormat(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	w := NewFileStreamWriter(func() bool { return true }, fileStream)

	line1 := RunLogsLineForTest("content 1")
	line1Str, err := line1.StructuredFormat()
	require.NoError(t, err)

	line2 := RunLogsLineForTest("content 2")
	line2Str, err := line2.StructuredFormat()
	require.NoError(t, err)

	w.UpdateLine(1, line1)
	w.UpdateLine(2, line2)
	w.Finish()

	lines := fileStream.GetRequest(settings.New()).ConsoleLines
	assert.Equal(t, line1Str, lines.GetOrZero(1))
	assert.Equal(t, line2Str, lines.GetOrZero(2))
}

func TestWritesLegacyFormat(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	w := NewFileStreamWriter(func() bool { return false }, fileStream)

	line1 := RunLogsLineForTest("content 1")
	line1Str := line1.LegacyFormat()

	line2 := RunLogsLineForTest("content 2")
	line2Str := line2.LegacyFormat()

	w.UpdateLine(1, line1)
	w.UpdateLine(2, line2)
	w.Finish()

	lines := fileStream.GetRequest(settings.New()).ConsoleLines
	assert.Equal(t, line1Str, lines.GetOrZero(1))
	assert.Equal(t, line2Str, lines.GetOrZero(2))
}
