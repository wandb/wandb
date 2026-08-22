package runlogs_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/filestreamtest"
	. "github.com/wandb/wandb/core/internal/runlogs"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sparselist"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func testTime() time.Time {
	return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
}

func newSender(
	fileStream *filestreamtest.FakeFileStream,
	params Params,
) *Sender {
	params.FileStreamOrNil = fileStream
	params.GetNow = testTime
	return New(params)
}

func consoleLines(
	t *testing.T,
	fileStream *filestreamtest.FakeFileStream,
) []sparselist.Run[string] {
	t.Helper()
	return fileStream.GetRequest(settings.New()).ConsoleLines.ToRuns()
}

func TestNumbersLinesInOrder(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	sender := newSender(fileStream, Params{})

	sender.StreamLine(&spb.RunLogRequest{Line: "first"})
	sender.StreamLine(&spb.RunLogRequest{Line: "second"})
	sender.Finish()

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				"2024-01-01T00:00:00.000000 first",
				"2024-01-01T00:00:00.000000 second",
			}},
		},
		consoleLines(t, fileStream))
}

func TestSplitsEmbeddedNewlines(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	sender := newSender(fileStream, Params{})

	sender.StreamLine(&spb.RunLogRequest{Line: "first\nsecond\n"})
	sender.Finish()

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				"2024-01-01T00:00:00.000000 first",
				"2024-01-01T00:00:00.000000 second",
			}},
		},
		consoleLines(t, fileStream))
}

func TestRecordLabelOverridesRunLabel(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	sender := newSender(fileStream, Params{Label: "scheduler"})

	sender.StreamLine(&spb.RunLogRequest{Line: "unlabeled"})
	sender.StreamLine(&spb.RunLogRequest{Line: "labeled", Label: "optuna"})
	sender.Finish()

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				"2024-01-01T00:00:00.000000 [scheduler] unlabeled",
				"2024-01-01T00:00:00.000000 [optuna] labeled",
			}},
		},
		consoleLines(t, fileStream))
}

func TestErrorLevelMarksTheLine(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	sender := newSender(fileStream, Params{})

	sender.StreamLine(&spb.RunLogRequest{
		Line:  "it broke",
		Level: spb.RunLogRequest_ERROR,
	})
	sender.Finish()

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				"ERROR 2024-01-01T00:00:00.000000 it broke",
			}},
		},
		consoleLines(t, fileStream))
}

func TestStructuredFormat(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	sender := newSender(fileStream, Params{
		Label:      "scheduler",
		Structured: func() bool { return true },
	})

	sender.StreamLine(&spb.RunLogRequest{
		Line:  "it broke",
		Label: "optuna",
		Level: spb.RunLogRequest_ERROR,
	})
	sender.Finish()

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				`{"level":"error","ts":"2024-01-01T00:00:00.000000",` +
					`"label":"optuna","content":"it broke"}`,
			}},
		},
		consoleLines(t, fileStream))
}

func TestDropsLinesAfterFinish(t *testing.T) {
	fileStream := filestreamtest.NewFakeFileStream()
	sender := newSender(fileStream, Params{})

	sender.Finish()
	sender.StreamLine(&spb.RunLogRequest{Line: "too late"})

	assert.Empty(t, consoleLines(t, fileStream))
}

func TestWithoutFileStream(t *testing.T) {
	sender := New(Params{GetNow: testTime})

	// Offline runs have no filestream; the line is dropped.
	sender.StreamLine(&spb.RunLogRequest{Line: "nowhere to go"})
	sender.Finish()
}
