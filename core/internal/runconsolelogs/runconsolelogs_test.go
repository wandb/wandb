package runconsolelogs_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/paths"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/runfilestest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sparselist"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestFileStreamUpdates(t *testing.T) {
	settings := settings.New()
	fileStream := filestreamtest.NewFakeFileStream()

	sender := New(Params{
		FilesDir:      t.TempDir(),
		EnableCapture: true,
		Logger:        observabilitytest.NewTestLogger(t),
		RunfilesUploaderOrNil: runfilestest.WithTestDefaults(t,
			runfilestest.Params{},
		),
		FileStreamOrNil: fileStream,
		GetNow: func() time.Time {
			return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
		},
	})

	sender.StreamLogs(&spb.OutputRawRecord{Line: "line1\n"})
	sender.StreamLogs(&spb.OutputRawRecord{Line: "line2\n"})
	sender.StreamLogs(&spb.OutputRawRecord{Line: "\x1b[Aline2 - modified\n"})
	sender.Finish()

	request := fileStream.GetRequest(settings)
	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				"ERROR 2024-01-01T00:00:00.000000 line1",
				"ERROR 2024-01-01T00:00:00.000000 line2 - modified",
			}},
		},
		request.ConsoleLines.ToRuns())
}

func TestFileStreamUpdatesDisabled(t *testing.T) {
	// Test that the filestream is not updated when capture is disabled.
	filesDir := t.TempDir()
	fileStream := filestreamtest.NewFakeFileStream()
	outputFile, _ := paths.Relative("output.log")

	sender := New(Params{
		FilesDir:      filesDir,
		EnableCapture: false,
		Logger:        observabilitytest.NewTestLogger(t),
		RunfilesUploaderOrNil: runfilestest.WithTestDefaults(t,
			runfilestest.Params{},
		),
		FileStreamOrNil: fileStream,
		GetNow: func() time.Time {
			return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
		},
	})

	sender.StreamLogs(&spb.OutputRawRecord{Line: "line1\n"})
	sender.StreamLogs(&spb.OutputRawRecord{Line: "line2\n"})
	sender.StreamLogs(&spb.OutputRawRecord{Line: "\x1b[Aline2 - modified\n"})
	sender.Finish()

	outputFilePath := filepath.Join(filesDir, string(*outputFile))
	_, err := os.Stat(outputFilePath)
	assert.True(t, os.IsNotExist(err))

	request := fileStream.GetRequest(settings.New())
	assert.Empty(t, request.ConsoleLines.ToRuns())
}

func TestSender_Multipart_WritesChunkAndUploadsOnFinish(t *testing.T) {
	dir := t.TempDir()
	uploader := NewFakeUploader()

	s := New(Params{
		FilesDir:              dir,
		EnableCapture:         true,
		Logger:                observabilitytest.NewTestLogger(t),
		RunfilesUploaderOrNil: uploader,
		Multipart:             true,
		ChunkMaxBytes:         1 << 30, // big: no rotation from size
		ChunkMaxSeconds:       0,       // no rotation from time
		GetNow: func() time.Time {
			return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
		},
	})

	// Write a couple lines and finish.
	s.StreamLogs(&spb.OutputRawRecord{Line: "line1\n"})
	s.StreamLogs(&spb.OutputRawRecord{Line: "line2\n"})
	s.Finish()

	// One chunk should exist under logs/, uploaded once at finish.
	chunks := getChunkFiles(t, dir)
	require.Equal(t, 1, len(chunks))
	assert.Len(t, uploader.uploadedPaths, 1)

	base := filepath.Base(chunks[0])
	assert.True(t, strings.HasPrefix(base, "output_"))
	assert.True(t, strings.HasSuffix(base, ".log"))
}

func TestSender_LabelChangesOutputFileName_SingleFile(t *testing.T) {
	dir := t.TempDir()

	s := New(Params{
		FilesDir:      dir,
		EnableCapture: true,
		Logger:        observabilitytest.NewTestLogger(t),
		Label:         "train", // safe: avoid depending on sanitizer internals
		GetNow: func() time.Time {
			return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
		},
	})

	s.StreamLogs(&spb.OutputRawRecord{Line: "hello\n"})
	s.Finish()

	want := filepath.Join(dir, "output_train.log")

	_, err := os.Stat(want)
	require.NoError(t, err, "expected labeled output file to exist")
}
