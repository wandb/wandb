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

// pop invokes [FileStreamState.Pop] without summary deltas, and with a test
// logger and printer.
func pop(
	t *testing.T,
	state *FileStreamState,
	request *FileStreamRequest,
) (*FileStreamRequestJSON, bool) {
	return popAccepting(t, state, false, request)
}

// popAccepting is [pop] with the given acceptSummaryDelta.
func popAccepting(
	t *testing.T,
	state *FileStreamState,
	acceptSummaryDelta bool,
	request *FileStreamRequest,
) (*FileStreamRequestJSON, bool) {
	return state.Pop(
		request,
		acceptSummaryDelta,
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

	json, hasMore := state.Pop(request, false, logger, printer)

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

// popSummaryLine pops the request and returns its summary line, if any,
// and whether it was marked as a delta.
func popSummaryLine(
	t *testing.T,
	state *FileStreamState,
	acceptSummaryDelta bool,
	request *FileStreamRequest,
) (string, bool) {
	t.Helper()
	json, _ := popAccepting(t, state, acceptSummaryDelta, request)
	chunk, ok := json.Files[SummaryFileName]
	if !ok {
		return "", false
	}
	assert.Len(t, chunk.Content, 1)
	return chunk.Content[0], json.SummaryDelta != nil && *json.SummaryDelta
}

func TestState_Pop_SummaryDelta(t *testing.T) {
	accept := true
	state := &FileStreamState{
		MaxFileLineSize: 999,
	}

	// The first summary of a stream is full.
	line, isDelta := popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
	assert.JSONEq(t, `{"a":1}`, line)
	assert.False(t, isDelta)

	line, isDelta = popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.True(t, isDelta)

	// A delta can't express a removal.
	removal := runsummary.FromProto(&spb.SummaryRecord{
		Remove: []*spb.SummaryItem{{Key: "a"}},
	})
	line, isDelta = popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: removal})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.False(t, isDelta)

	line, isDelta = popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("c", "3")})
	assert.JSONEq(t, `{"c":3}`, line)
	assert.True(t, isDelta)

	// Without deltas the full summary is sent, and when they come back the
	// first summary is full again.
	accept = false
	line, isDelta = popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("d", "4")})
	assert.JSONEq(t, `{"b":2,"c":3,"d":4}`, line)
	assert.False(t, isDelta)
	accept = true
	line, isDelta = popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("e", "5")})
	assert.JSONEq(t, `{"b":2,"c":3,"d":4,"e":5}`, line)
	assert.False(t, isDelta)
	line, isDelta = popSummaryLine(t, state, accept,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("f", "6")})
	assert.JSONEq(t, `{"f":6}`, line)
	assert.True(t, isDelta)
}

func TestState_Pop_SummaryDeltaThenComplete(t *testing.T) {
	for _, tc := range []struct {
		name    string
		request *FileStreamRequest
		want    string
	}{
		{"no new changes", &FileStreamRequest{Complete: true}, `{"a":1,"b":2}`},
		{
			"new changes",
			&FileStreamRequest{Complete: true, SummaryUpdates: summaryUpdate("c", "3")},
			`{"a":1,"b":2,"c":3}`,
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			state := &FileStreamState{
				MaxFileLineSize: 999,
			}
			popSummaryLine(t, state, true, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
			popSummaryLine(t, state, true, &FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})

			line, isDelta := popSummaryLine(t, state, true, tc.request)

			assert.JSONEq(t, tc.want, line)
			assert.False(t, isDelta)
		})
	}
}

func TestState_Pop_SummaryDeltaThatDoesNotFitAccumulates(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize:     999,
		MaxRequestSizeBytes: 10,
	}
	popSummaryLine(t, state, true, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})

	request := &FileStreamRequest{
		HistoryLines:   []string{"the history"},
		SummaryUpdates: summaryUpdate("b", "2"),
	}
	json, hasMore := popAccepting(t, state, true, request)
	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)

	request.SummaryUpdates = summaryUpdate("c", "3")
	line, isDelta := popSummaryLine(t, state, true, request)
	assert.JSONEq(t, `{"b":2,"c":3}`, line)
	assert.True(t, isDelta)
}

func TestState_Pop_UnsentSummaryDeltaNoLongerAccepted(t *testing.T) {
	accept := true
	state := &FileStreamState{
		MaxFileLineSize:     999,
		MaxRequestSizeBytes: 10,
	}
	popSummaryLine(t, state, accept, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
	request := &FileStreamRequest{
		HistoryLines:   []string{"the history"},
		SummaryUpdates: summaryUpdate("b", "2"),
	}
	popAccepting(t, state, accept, request)

	accept = false
	line, isDelta := popSummaryLine(t, state, accept, request)

	assert.JSONEq(t, `{"a":1,"b":2}`, line)
	assert.False(t, isDelta)
}

func TestState_Pop_SentSummaryDeltaNoLongerAccepted(t *testing.T) {
	accept := true
	state := &FileStreamState{
		MaxFileLineSize:     999,
		MaxRequestSizeBytes: 999,
	}
	popSummaryLine(t, state, accept, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})
	popSummaryLine(t, state, accept, &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "2")})

	// The next request carries the full summary even with no summary changes.
	accept = false
	line, isDelta := popSummaryLine(t, state, accept,
		&FileStreamRequest{EventsLines: []string{`{"cpu":1}`}})
	assert.JSONEq(t, `{"a":2}`, line)
	assert.False(t, isDelta)

	// Only once.
	line, _ = popSummaryLine(t, state, accept,
		&FileStreamRequest{EventsLines: []string{`{"cpu":2}`}})
	assert.Empty(t, line)
}

func TestState_Pop_SummaryDeltaLeavesOutHistoryValues(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize: 999,
	}
	logged := func(valueJSON string) *runsummary.Updates {
		return runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{
				{Key: "acc", ValueJson: valueJSON, FromHistory: true},
			},
		})
	}

	line, _ := popSummaryLine(t, state, true,
		&FileStreamRequest{SummaryUpdates: logged("0.5")})
	assert.JSONEq(t, `{"acc":0.5}`, line)

	updates := logged("0.6")
	updates.Merge(summaryUpdate("best", "0.7"))
	line, isDelta := popSummaryLine(t, state, true,
		&FileStreamRequest{SummaryUpdates: updates})
	assert.JSONEq(t, `{"best":0.7}`, line)
	assert.True(t, isDelta)

	line, isDelta = popSummaryLine(t, state, true, &FileStreamRequest{Complete: true})
	assert.JSONEq(t, `{"acc":0.6,"best":0.7}`, line)
	assert.False(t, isDelta)
}

func TestState_Pop_SummaryDeltaAfterTooLargeFullSummary(t *testing.T) {
	state := &FileStreamState{
		MaxFileLineSize: 12,
	}

	line, _ := popSummaryLine(t, state, true, &FileStreamRequest{
		SummaryUpdates: summaryUpdate("big", `"a long value"`),
	})
	assert.Empty(t, line)

	line, isDelta := popSummaryLine(t, state, true,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.True(t, isDelta)
}
