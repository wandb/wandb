package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestSizeLimit_HugeLine_SentAlone(t *testing.T) {
	reader, isTruncated := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"too large", "next"}},
		0,
	)

	json := reader.GetJSON(&FileStreamState{})
	next, done := reader.Next()

	// Even though "too large" is above the size limit (0) we do want
	// to eventually send it. There are other guards elsewhere to avoid
	// this case and inform the user.
	assert.True(t, isTruncated)
	assert.Equal(t, []string{"too large"}, json.Files[HistoryFileName].Content)
	assert.Equal(t, []string{"next"}, next.HistoryLines)
	assert.False(t, done)
}

func TestHistory_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{HistoryLines: []string{"original"}}
	req2 := &FileStreamRequest{HistoryLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.HistoryLines)
}

func TestHistory_ReadFull(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"one", "two"}}, 999)
	state := &FileStreamState{HistoryLineNum: 5}

	json := reader.GetJSON(state)
	next, done := reader.Next()

	assert.Equal(t, 7, state.HistoryLineNum)
	assert.Equal(t, 5, json.Files[HistoryFileName].Offset)
	assert.Equal(t, []string{"one", "two"}, json.Files[HistoryFileName].Content)
	assert.Empty(t, next.HistoryLines)
	assert.True(t, done)
}

func TestHistory_ReadPartial(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"one", "two"}}, 3)
	state := &FileStreamState{HistoryLineNum: 5}

	json := reader.GetJSON(state)
	next, done := reader.Next()

	assert.Equal(t, 6, state.HistoryLineNum)
	assert.Equal(t, 5, json.Files[HistoryFileName].Offset)
	assert.Equal(t, []string{"one"}, json.Files[HistoryFileName].Content)
	assert.Equal(t, []string{"two"}, next.HistoryLines)
	assert.False(t, done)
}

func TestEvents_MergeAppends(t *testing.T) {
	req1 := &FileStreamRequest{EventsLines: []string{"original"}}
	req2 := &FileStreamRequest{EventsLines: []string{"new"}}

	req1.Merge(req2)

	assert.Equal(t, []string{"original", "new"}, req1.EventsLines)
}

func TestEvents_ReadFull(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{EventsLines: []string{"one", "two"}}, 999)
	state := &FileStreamState{EventsLineNum: 5}

	json := reader.GetJSON(state)
	next, done := reader.Next()

	assert.Equal(t, 7, state.EventsLineNum)
	assert.Equal(t, 5, json.Files[EventsFileName].Offset)
	assert.Equal(t, []string{"one", "two"}, json.Files[EventsFileName].Content)
	assert.Empty(t, next.EventsLines)
	assert.True(t, done)
}

func TestEvents_ReadPartial(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{EventsLines: []string{"one", "two"}}, 3)
	state := &FileStreamState{EventsLineNum: 5}

	json := reader.GetJSON(state)
	next, done := reader.Next()

	assert.Equal(t, 6, state.EventsLineNum)
	assert.Equal(t, 5, json.Files[EventsFileName].Offset)
	assert.Equal(t, []string{"one"}, json.Files[EventsFileName].Content)
	assert.Equal(t, []string{"two"}, next.EventsLines)
	assert.False(t, done)
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
	reader, _ := NewRequestReader(&FileStreamRequest{LatestSummary: "summary"}, 99)
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

func TestConsole_ReadFull(t *testing.T) {
	req := &FileStreamRequest{}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(1, "line 1")
	reader, _ := NewRequestReader(req, 999)
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

func TestConsole_ReadPartial_OneLineBlock(t *testing.T) {
	req := &FileStreamRequest{}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(1, "line 1")
	reader, _ := NewRequestReader(req, 6)

	json := reader.GetJSON(&FileStreamState{})
	next, done := reader.Next()

	assert.Equal(t, []string{"line 0"}, json.Files[OutputFileName].Content)
	assert.Equal(t, 1, next.ConsoleLines.Len())
	assert.Equal(t, "line 1", next.ConsoleLines.GetOrZero(1))
	assert.False(t, done)
}

func TestConsole_ReadPartial_ManyLineBlocks(t *testing.T) {
	req := &FileStreamRequest{}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(99, "line 99")
	reader, _ := NewRequestReader(req, 6)

	json := reader.GetJSON(&FileStreamState{})
	next, done := reader.Next()

	assert.Equal(t, []string{"line 0"}, json.Files[OutputFileName].Content)
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
	reader, _ := NewRequestReader(&FileStreamRequest{
		UploadedFiles: map[string]struct{}{
			"file1": {},
			"file2": {},
		},
	}, 999)

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
	reader, _ := NewRequestReader(
		&FileStreamRequest{Complete: true, ExitCode: 5}, 99)

	json := reader.GetJSON(&FileStreamState{})

	assert.True(t, *json.Complete)
	assert.EqualValues(t, 5, *json.ExitCode)
}

func TestExitCode_Read_NotDone(t *testing.T) {
	// Non-consecutive console lines can't be sent in one request.
	req := &FileStreamRequest{Complete: true, ExitCode: 5}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(9, "line 9")
	reader, _ := NewRequestReader(req, 99)

	json := reader.GetJSON(&FileStreamState{})

	assert.Nil(t, json.Complete)
	assert.Nil(t, json.ExitCode)
}
