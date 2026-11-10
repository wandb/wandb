package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/sparselist"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// pop invokes [FileStreamState.Pop] with a test logger and printer.
func pop(
	t *testing.T,
	state *FileStreamState,
	request *FileStreamRequest,
) (*FileStreamRequestJSON, bool) {
	return state.Pop(
		request,
		observabilitytest.NewTestLogger(t),
		observability.NewPrinter(0),
	)
}

func TestState_IsAtSizeLimit_NotAtLimit(t *testing.T) {
	state := &FileStreamState{MaxRequestSizeBytes: 1}
	request := &FileStreamRequest{}

	assert.False(t, state.IsAtSizeLimit(request))
}

func TestState_IsAtSizeLimit_History(t *testing.T) {
	state := &FileStreamState{MaxRequestSizeBytes: 10}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"one", "two", "this line is too long"}

	assert.True(t, state.IsAtSizeLimit(request))
}

func TestState_IsAtSizeLimit_Events(t *testing.T) {
	state := &FileStreamState{MaxRequestSizeBytes: 10}
	request := &FileStreamRequest{}
	request.EventsLines = []string{"one", "two", "this line is too long"}

	assert.True(t, state.IsAtSizeLimit(request))
}

func TestState_IsAtSizeLimit_SummaryUpdates(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 10,
		LastRunSummarySize:  11,
	}
	request := &FileStreamRequest{}
	request.SummaryUpdates = runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: "xyz", ValueJson: "1"}},
	})

	assert.True(t, state.IsAtSizeLimit(request))
}

func TestState_IsAtSizeLimit_UnsentSummary(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 10,
		LastRunSummarySize:  26,
		UnsentSummary:       "this is 26 characters long",
	}
	request := &FileStreamRequest{}

	assert.True(t, state.IsAtSizeLimit(request))
}

func TestState_IsAtSizeLimit_Console(t *testing.T) {
	state := &FileStreamState{MaxRequestSizeBytes: 10}
	request := &FileStreamRequest{}
	request.ConsoleLines = &sparselist.SparseList[string]{}
	request.ConsoleLines.Put(0, "one")
	request.ConsoleLines.Put(1, "two")
	request.ConsoleLines.Put(2, "this line is too long")

	assert.True(t, state.IsAtSizeLimit(request))
}

func TestState_IsAtSizeLimit_ConsoleSmallRun(t *testing.T) {
	state := &FileStreamState{MaxRequestSizeBytes: 10}
	request := &FileStreamRequest{}
	request.ConsoleLines = &sparselist.SparseList[string]{}
	request.ConsoleLines.Put(0, "one")
	request.ConsoleLines.Put(1, "two")
	request.ConsoleLines.Put(10, "too long but in a different run")

	assert.False(t, state.IsAtSizeLimit(request))
}

func TestState_Pop_HasSomethingEvenIfOverSizeLimit(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"this line is too long"}

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	assert.Equal(t,
		[]string{"this line is too long"},
		json.Files[HistoryFileName].Content)
}

func TestState_Pop_OmitsFilesIfNotUpdated(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}

	json, _ := pop(t, state, request)

	assert.Empty(t, json.Files)
}

func TestState_Pop_FullHistory(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 99,
		HistoryLineNum:      7,
	}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"one", "two", "three"}

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	chunk := json.Files[HistoryFileName]
	assert.Equal(t, []string{"one", "two", "three"}, chunk.Content)
	assert.Equal(t, 7, chunk.Offset)
	assert.Empty(t, request.HistoryLines)
	assert.Equal(t, 10, state.HistoryLineNum)
}

func TestState_Pop_PartialHistory(t *testing.T) {
	state := &FileStreamState{HistoryLineNum: 7}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"one", "two", "three"}

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	chunk := json.Files[HistoryFileName]
	assert.Equal(t, []string{"one"}, chunk.Content)
	assert.Equal(t, 7, chunk.Offset)
	assert.Equal(t, []string{"two", "three"}, request.HistoryLines)
	assert.Equal(t, 8, state.HistoryLineNum)
}

func TestState_Pop_FullEvents(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 99,
		EventsLineNum:       7,
	}
	request := &FileStreamRequest{}
	request.EventsLines = []string{"one", "two", "three"}

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	chunk := json.Files[EventsFileName]
	assert.Equal(t, []string{"one", "two", "three"}, chunk.Content)
	assert.Equal(t, 7, chunk.Offset)
	assert.Empty(t, request.EventsLines)
	assert.Equal(t, 10, state.EventsLineNum)
}

func TestState_Pop_PartialEvents(t *testing.T) {
	state := &FileStreamState{EventsLineNum: 7}
	request := &FileStreamRequest{}
	request.EventsLines = []string{"one", "two", "three"}

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	chunk := json.Files[EventsFileName]
	assert.Equal(t, []string{"one"}, chunk.Content)
	assert.Equal(t, 7, chunk.Offset)
	assert.Equal(t, []string{"two", "three"}, request.EventsLines)
	assert.Equal(t, 8, state.EventsLineNum)
}

func TestState_Pop_AllSummaryUpdates(t *testing.T) {
	state := &FileStreamState{MaxFileLineSize: 99, SummaryLineNum: 7}
	request := &FileStreamRequest{}
	request.SummaryUpdates = runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: "xyz", ValueJson: "9"}},
	})

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	chunk := json.Files[SummaryFileName]
	assert.Equal(t, []string{`{"xyz":9}`}, chunk.Content)
	assert.Equal(t, 7, chunk.Offset)
	assert.Nil(t, request.SummaryUpdates)
	assert.Zero(t, state.UnsentSummary)
	assert.Equal(t, 9, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum) // never updated; see docs
}

func TestState_Pop_AllUnsentSummary(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize:    99,
		SummaryLineNum:     7,
		UnsentSummary:      "test summary",
		LastRunSummarySize: 12,
	}
	request := &FileStreamRequest{}

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	chunk := json.Files[SummaryFileName]
	assert.Equal(t, []string{`test summary`}, chunk.Content)
	assert.Equal(t, 7, chunk.Offset)
	assert.Nil(t, request.SummaryUpdates)
	assert.Zero(t, state.UnsentSummary)
	assert.Equal(t, 12, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum) // never updated; see docs
}

func TestState_Pop_SummaryUpdatesTooLarge(t *testing.T) {
	state := &FileStreamState{MaxFileLineSize: 99, SummaryLineNum: 7}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"the history"}
	request.SummaryUpdates = runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "key", ValueJson: `"value"`},
		},
	})

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)
	assert.Nil(t, request.SummaryUpdates)
	assert.Equal(t, `{"key":"value"}`, state.UnsentSummary)
	assert.Equal(t, 15, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum)
}

func TestState_Pop_UnsentSummaryTooLarge(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize:    99,
		SummaryLineNum:     7,
		UnsentSummary:      "unsent summary",
		LastRunSummarySize: 14,
	}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"the history"}

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)
	assert.Equal(t, "unsent summary", state.UnsentSummary)
	assert.Equal(t, 14, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum)
}

func TestState_Pop_SummaryLineTooLong(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize:    1,
		SummaryLineNum:     7,
		UnsentSummary:      "too long",
		LastRunSummarySize: 8,
	}
	request := &FileStreamRequest{}
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	printer := observability.NewPrinter(100)

	json, hasMore := state.Pop(request, logger, printer)

	assert.False(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)
	assert.Zero(t, state.UnsentSummary)
	assert.Equal(t, 8, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum)
	assert.Contains(t,
		logs.String(),
		"filestream: run summary line too long, skipping")
	messages := printer.Read()
	assert.Len(t, messages, 1)
	assert.Equal(t, observability.Warning, messages[0].Severity)
	assert.Equal(t,
		"Skipped uploading summary data that exceeded size limit"+
			" (8 > 1 bytes).",
		messages[0].Content)
}

func TestState_Pop_FullConsoleLines(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 99,
		ConsoleLineOffset:   7,
	}
	request := &FileStreamRequest{}
	request.ConsoleLines = &sparselist.SparseList[string]{}
	request.ConsoleLines.Put(10, "line 17")
	request.ConsoleLines.Put(11, "line 18")

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	chunk := json.Files[OutputFileName]
	assert.Equal(t, []string{"line 17", "line 18"}, chunk.Content)
	assert.Equal(t, 17, chunk.Offset)
	assert.Zero(t, request.ConsoleLines.Len())
	assert.Equal(t, 7, state.ConsoleLineOffset) // never updated
}

func TestState_Pop_ConsoleLinesLimitedBySize(t *testing.T) {
	state := &FileStreamState{ConsoleLineOffset: 7}
	request := &FileStreamRequest{}
	request.ConsoleLines = &sparselist.SparseList[string]{}
	request.ConsoleLines.Put(6, "line 13")
	request.ConsoleLines.Put(7, "line 14")

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	chunk := json.Files[OutputFileName]
	assert.Equal(t, []string{"line 13"}, chunk.Content)
	assert.Equal(t, 13, chunk.Offset)
	assert.Equal(t, 1, request.ConsoleLines.Len())
	assert.Equal(t, 7, state.ConsoleLineOffset) // never updated
}

func TestState_Pop_ConsoleLinesMoreThanOneRun(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 99,
		ConsoleLineOffset:   7,
	}
	request := &FileStreamRequest{}
	request.ConsoleLines = &sparselist.SparseList[string]{}
	request.ConsoleLines.Put(10, "run1_a")
	request.ConsoleLines.Put(11, "run1_b")
	request.ConsoleLines.Put(20, "run2_a")

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	chunk := json.Files[OutputFileName]
	assert.Equal(t, []string{"run1_a", "run1_b"}, chunk.Content)
	assert.Equal(t, 17, chunk.Offset)
	assert.Equal(t, 1, request.ConsoleLines.Len())
	assert.Equal(t, 7, state.ConsoleLineOffset) // never updated
}

func TestState_Pop_UploadedFiles(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}
	request.UploadedFiles = map[string]struct{}{
		"file1": {},
		"file2": {},
	}

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	assert.ElementsMatch(t, []string{"file1", "file2"}, json.Uploaded)
	assert.Empty(t, request.UploadedFiles)
}

func TestState_Pop_Preempting(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}
	request.Preempting = true

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	assert.True(t, *json.Preempting)
	assert.False(t, request.Preempting)
}

func TestState_Pop_ExitCode(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}
	request.Complete = true
	request.ExitCode = 1

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	assert.True(t, *json.Complete)
	assert.EqualValues(t, 1, *json.ExitCode)
	assert.True(t, request.Complete)           // not changed
	assert.EqualValues(t, 1, request.ExitCode) // not changed
}

func TestState_Pop_NoExitCodeIfNotComplete(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}
	request.Complete = false
	request.ExitCode = 1

	json, hasMore := pop(t, state, request)

	assert.False(t, hasMore)
	assert.Nil(t, json.Complete)
	assert.Nil(t, json.ExitCode)
}

func TestState_Pop_NoExitCodeIfPartial(t *testing.T) {
	state := &FileStreamState{}
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"sent", "not sent due to size"}
	request.Complete = true
	request.ExitCode = 1

	json, hasMore := pop(t, state, request)

	assert.True(t, hasMore)
	assert.Nil(t, json.Complete)
	assert.Nil(t, json.ExitCode)
}

// summaryUpdate returns updates that set key to the JSON value.
func summaryUpdate(key, valueJSON string) *runsummary.Updates {
	return runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: key, ValueJson: valueJSON}},
	})
}

// popSummary pops a request carrying the summary updates and returns the
// summary line sent and whether it was marked as a delta.
func popSummary(
	t *testing.T,
	state *FileStreamState,
	request *FileStreamRequest,
) (string, bool) {
	t.Helper()
	json, _ := pop(t, state, request)
	chunk, ok := json.Files[SummaryFileName]
	if !ok {
		return "", false
	}
	assert.Len(t, chunk.Content, 1)
	return chunk.Content[0], json.SummaryDelta != nil && *json.SummaryDelta
}

func TestState_Pop_SummaryDelta(t *testing.T) {
	explicit := true
	state := &FileStreamState{
		MaxFileLineSize: 999,
		ExplicitSummary: func() bool { return explicit },
	}

	// The first summary of a stream is full even when deltas are on.
	line, isDelta := popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
	assert.JSONEq(t, `{"a":1}`, line)
	assert.False(t, isDelta)

	// After that, only the changes go out.
	line, isDelta = popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.True(t, isDelta)

	// A removal can't be expressed as a delta.
	removal := runsummary.FromProto(&spb.SummaryRecord{
		Remove: []*spb.SummaryItem{{Key: "a"}},
	})
	line, isDelta = popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: removal})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.False(t, isDelta)

	// When the backend turns deltas off, the next summary is full.
	line, isDelta = popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("c", "3")})
	assert.JSONEq(t, `{"c":3}`, line)
	assert.True(t, isDelta)
	explicit = false
	line, isDelta = popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("d", "4")})
	assert.JSONEq(t, `{"b":2,"c":3,"d":4}`, line)
	assert.False(t, isDelta)
}

func TestState_Pop_SummaryDeltaThenComplete(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize: 999,
		ExplicitSummary: func() bool { return true },
	}
	popSummary(t, state, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
	popSummary(t, state, &FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})

	// The final request carries the full summary even with no new changes.
	line, isDelta := popSummary(t, state, &FileStreamRequest{Complete: true})
	assert.JSONEq(t, `{"a":1,"b":2}`, line)
	assert.False(t, isDelta)

	// And with new changes, the full summary instead of their delta.
	state = &FileStreamState{
		MaxFileLineSize: 999,
		ExplicitSummary: func() bool { return true },
	}
	popSummary(t, state, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
	line, isDelta = popSummary(t, state, &FileStreamRequest{
		SummaryUpdates: summaryUpdate("b", "2"),
		Complete:       true,
	})
	assert.JSONEq(t, `{"a":1,"b":2}`, line)
	assert.False(t, isDelta)
}

func TestState_Pop_SummaryDeltaThatDoesNotFitAccumulates(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize:     999,
		MaxRequestSizeBytes: 10,
		ExplicitSummary:     func() bool { return true },
	}
	popSummary(t, state, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})

	// The history fills the request, so the delta waits.
	request := &FileStreamRequest{
		HistoryLines:   []string{"the history"},
		SummaryUpdates: summaryUpdate("b", "2"),
	}
	json, hasMore := pop(t, state, request)
	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)

	// Later changes join the waiting delta.
	request.SummaryUpdates = summaryUpdate("c", "3")
	line, isDelta := popSummary(t, state, request)
	assert.JSONEq(t, `{"b":2,"c":3}`, line)
	assert.True(t, isDelta)
}

func TestState_Pop_SummaryWithoutExplicitSummaryIsFull(t *testing.T) {
	state := &FileStreamState{MaxFileLineSize: 999}
	popSummary(t, state, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})

	line, isDelta := popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})

	assert.JSONEq(t, `{"a":1,"b":2}`, line)
	assert.False(t, isDelta)
}

func TestState_Pop_SummaryDeltaAfterTooLargeFullSummary(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize: 12,
		ExplicitSummary: func() bool { return true },
	}

	// The first, full summary is over the line limit and is dropped.
	line, _ := popSummary(t, state, &FileStreamRequest{
		SummaryUpdates: summaryUpdate("big", `"a long value"`),
	})
	assert.Empty(t, line)

	// The changes after it still go out.
	line, isDelta := popSummary(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.True(t, isDelta)
}
