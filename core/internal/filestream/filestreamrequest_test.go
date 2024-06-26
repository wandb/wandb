package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestGet_NotFinal(t *testing.T) {
	exitCode := int32(123)
	complete := true
	buf := &FileStreamRequestBuffer{ExitCode: &exitCode, Complete: &complete}

	req, isDone, _ := buf.Get()

	assert.False(t, isDone)
	assert.Nil(t, req.ExitCode)
	assert.Nil(t, req.Complete)
}

func TestGet_Final(t *testing.T) {
	exitCode := int32(123)
	complete := true
	buf := &FileStreamRequestBuffer{ExitCode: &exitCode, Complete: &complete}

	buf.Finalize()
	req, isDone, _ := buf.Get()

	assert.True(t, isDone)
	assert.Equal(t, &exitCode, req.ExitCode)
	assert.Equal(t, &complete, req.Complete)
}

func TestGet_History(t *testing.T) {
	buf := &FileStreamRequestBuffer{
		HistoryLineNum: 3,
		HistoryLines:   []string{"hist1", "hist2"},
	}

	req, _, advance := buf.Get()
	next := advance.Advance()

	assert.Equal(t, 3, req.Files[HistoryFileName].Offset)
	assert.Equal(t,
		[]string{"hist1", "hist2"},
		req.Files[HistoryFileName].Content)
	assert.Equal(t, 5, next.HistoryLineNum)
	assert.Empty(t, next.HistoryLines)
}

func TestGet_Events(t *testing.T) {
	buf := &FileStreamRequestBuffer{
		EventsLineNum: 7,
		EventsLines:   []string{"1", "2"},
	}

	req, _, advance := buf.Get()
	next := advance.Advance()

	assert.Equal(t, 7, req.Files[EventsFileName].Offset)
	assert.Equal(t,
		[]string{"1", "2"},
		req.Files[EventsFileName].Content)
	assert.Equal(t, 9, next.EventsLineNum)
	assert.Empty(t, next.EventsLines)
}

func TestGet_Summary(t *testing.T) {
	buf := &FileStreamRequestBuffer{
		SummaryLineNum: 714,
		LatestSummary:  "summary",
	}

	req, _, advance := buf.Get()
	next := advance.Advance()

	assert.Equal(t, 714, req.Files[SummaryFileName].Offset)
	assert.Equal(t, []string{"summary"}, req.Files[SummaryFileName].Content)
	assert.Equal(t, 714, next.SummaryLineNum)
	assert.Empty(t, next.LatestSummary)
}

func TestGet_Console(t *testing.T) {
	buf := &FileStreamRequestBuffer{ConsoleLogLineOffset: 13}
	buf.ConsoleLogUpdates.Put(3, "line 16")
	buf.ConsoleLogUpdates.Put(4, "line 17")
	buf.ConsoleLogUpdates.Put(10, "line 23")

	req, _, advance := buf.Get()
	next := advance.Advance()

	assert.Equal(t, 16, req.Files[OutputFileName].Offset)
	assert.Equal(t,
		[]string{"line 16", "line 17"},
		req.Files[OutputFileName].Content)
	assert.Equal(t, 13, next.ConsoleLogLineOffset)
	assert.Equal(t, 1, next.ConsoleLogUpdates.Len())
	assert.Equal(t,
		[]sparselist.Run[string]{{Start: 10, Items: []string{"line 23"}}},
		next.ConsoleLogUpdates.ToRuns())
}

func TestGet_Console_Finalizing(t *testing.T) {
	// Nonconsecutive lines cannot be uploaded in the same request
	// due to filestream limitations.
	buf := &FileStreamRequestBuffer{}
	buf.ConsoleLogUpdates.Put(0, "line 0")
	buf.ConsoleLogUpdates.Put(5, "line 5")

	buf.Finalize()
	_, isDone, advance := buf.Get()

	assert.False(t, isDone)

	buf = advance.Advance()
	_, isDone, _ = buf.Get()

	assert.True(t, isDone)
}

func TestGet_UploadedFiles(t *testing.T) {
	buf := &FileStreamRequestBuffer{
		UploadedFiles: []string{"file1", "file2", "file3"},
	}

	req, _, advance := buf.Get()
	next := advance.Advance()

	assert.Equal(t,
		[]string{"file1", "file2", "file3"},
		req.Uploaded)
	assert.Empty(t, next.UploadedFiles)
}

func TestGet_Preempting(t *testing.T) {
	boolTrue := true
	buf := &FileStreamRequestBuffer{Preempting: &boolTrue}

	req, _, advance := buf.Get()
	next := advance.Advance()

	assert.Equal(t, &boolTrue, req.Preempting)
	assert.Nil(t, next.Preempting)
}
