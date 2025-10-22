package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestHistory_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{HistoryLines: []string{"original"}}
	req2 := &FileStreamRequest{HistoryLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.HistoryLines)
}

func TestEvents_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{EventsLines: []string{"original"}}
	req2 := &FileStreamRequest{EventsLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.EventsLines)
}

func TestSummary_MergeTakesLatest(t *testing.T) {
	req1 := &FileStreamRequest{LatestSummary: "first"}
	req2 := &FileStreamRequest{LatestSummary: "second"}

	req1.Merge(req2)

	assert.Equal(t, "second", req1.LatestSummary)
}

func TestSummary_MergeIgnoresEmpty(t *testing.T) {
	req1 := &FileStreamRequest{LatestSummary: "first"}
	req2 := &FileStreamRequest{}

	req1.Merge(req2)

	assert.Equal(t, "first", req1.LatestSummary)
}

func TestConsole_MergeUpdatesPreferringLast(t *testing.T) {
	req1 := &FileStreamRequest{}
	req1.ConsoleLines.Put(0, "req1 - 0")
	req1.ConsoleLines.Put(5, "req1 - 5")
	req2 := &FileStreamRequest{}
	req2.ConsoleLines.Put(0, "req2 - 0")
	req2.ConsoleLines.Put(6, "req2 - 6")

	req1.Merge(req2)

	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{"req2 - 0"}},
			{Start: 5, Items: []string{"req1 - 5", "req2 - 6"}},
		},
		req1.ConsoleLines.ToRuns())
}

func TestUploadedFiles_MergeIsUnion(t *testing.T) {
	req1 := &FileStreamRequest{UploadedFiles: map[string]struct{}{
		"file1": {},
		"file2": {},
	}}
	req2 := &FileStreamRequest{UploadedFiles: map[string]struct{}{
		"file3": {},
	}}

	req1.Merge(req2)

	assert.Equal(t, map[string]struct{}{
		"file1": {},
		"file2": {},
		"file3": {},
	}, req1.UploadedFiles)
}

func TestExitCode_MergeTakesLatest(t *testing.T) {
	req1 := &FileStreamRequest{Complete: true, ExitCode: 111}
	req2 := &FileStreamRequest{Complete: true, ExitCode: 222}

	req1.Merge(req2)

	assert.True(t, req1.Complete)
	assert.EqualValues(t, 222, req1.ExitCode)
}

func TestExitCode_MergeIgnoresIfNotComplete(t *testing.T) {
	req1 := &FileStreamRequest{Complete: true, ExitCode: 111}
	req2 := &FileStreamRequest{Complete: false, ExitCode: 222}

	req1.Merge(req2)

	assert.True(t, req1.Complete)
	assert.EqualValues(t, 111, req1.ExitCode)
}
