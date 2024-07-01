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

func TestHistory_Read(t *testing.T) {
	reader := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"one", "two"}})
	state := &FileStreamState{HistoryLineNum: 5}

	json := reader.GetJSON(state)
	next, _ := reader.Next()

	assert.Equal(t, 7, state.HistoryLineNum)
	assert.Equal(t, 5, json.Files[HistoryFileName].Offset)
	assert.Equal(t, []string{"one", "two"}, json.Files[HistoryFileName].Content)
	assert.Empty(t, next.HistoryLines)
}

func TestEvents_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{EventsLines: []string{"original"}}
	req2 := &FileStreamRequest{EventsLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.EventsLines)
}

func TestEvents_Read(t *testing.T) {
	reader := NewRequestReader(
		&FileStreamRequest{EventsLines: []string{"one", "two"}})
	state := &FileStreamState{EventsLineNum: 5}

	json := reader.GetJSON(state)
	next, _ := reader.Next()

	assert.Equal(t, 7, state.EventsLineNum)
	assert.Equal(t, 5, json.Files[EventsFileName].Offset)
	assert.Equal(t, []string{"one", "two"}, json.Files[EventsFileName].Content)
	assert.Empty(t, next.EventsLines)
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

func TestSummary_Read(t *testing.T) {
	reader := NewRequestReader(&FileStreamRequest{LatestSummary: "summary"})
	state := &FileStreamState{SummaryLineNum: 9}

	json := reader.GetJSON(state)
	next, _ := reader.Next()

	assert.Equal(t, 9, state.SummaryLineNum) // unchanged!
	assert.Equal(t, 9, json.Files[SummaryFileName].Offset)
	assert.Equal(t, []string{"summary"}, json.Files[SummaryFileName].Content)
	assert.Empty(t, next.LatestSummary)
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

func TestConsole_Read_ConsecutiveLines(t *testing.T) {
	req := &FileStreamRequest{}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(1, "line 1")
	reader := NewRequestReader(req)
	state := &FileStreamState{ConsoleLineOffset: 1}

	json := reader.GetJSON(state)
	next, done := reader.Next()

	assert.Equal(t, 1, state.ConsoleLineOffset) // unchanged!
	assert.Equal(t, 1, json.Files[OutputFileName].Offset)
	assert.Equal(t,
		[]string{"line 0", "line 1"},
		json.Files[OutputFileName].Content)
	assert.Equal(t, 0, next.ConsoleLines.Len())
	assert.True(t, done)
}

func TestConsole_Read_NonconsecutiveLines(t *testing.T) {
	req := &FileStreamRequest{}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(1, "line 1")
	req.ConsoleLines.Put(99, "line 99")
	reader := NewRequestReader(req)

	json := reader.GetJSON(&FileStreamState{})
	next, done := reader.Next()

	// Only the first run of lines is sent.
	assert.Equal(t,
		[]string{"line 0", "line 1"},
		json.Files[OutputFileName].Content)
	// The rest of the lines are in the "next" request.
	assert.Equal(t, 1, next.ConsoleLines.Len())
	assert.Equal(t, "line 99", next.ConsoleLines.GetOrZero(99))
	assert.False(t, done)
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

func TestUploadedFiles_Read(t *testing.T) {
	reader := NewRequestReader(&FileStreamRequest{
		UploadedFiles: map[string]struct{}{
			"file1": {},
			"file2": {},
		},
	})

	json := reader.GetJSON(&FileStreamState{})
	next, _ := reader.Next()

	assert.Len(t, json.Uploaded, 2)
	assert.Contains(t, json.Uploaded, "file1")
	assert.Contains(t, json.Uploaded, "file2")
	assert.Empty(t, next.UploadedFiles)
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

func TestExitCode_Read_Done(t *testing.T) {
	reader := NewRequestReader(&FileStreamRequest{Complete: true, ExitCode: 5})

	json := reader.GetJSON(&FileStreamState{})

	assert.True(t, *json.Complete)
	assert.EqualValues(t, 5, *json.ExitCode)
}

func TestExitCode_Read_NotDone(t *testing.T) {
	// Non-consecutive console lines can't be sent in one request.
	req := &FileStreamRequest{Complete: true, ExitCode: 5}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(9, "line 9")
	reader := NewRequestReader(req)

	json := reader.GetJSON(&FileStreamState{})

	assert.Nil(t, json.Complete)
	assert.Nil(t, json.ExitCode)
}
