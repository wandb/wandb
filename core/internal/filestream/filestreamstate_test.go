package filestream_test

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

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
	state.Logger = observabilitytest.NewTestLogger(t)
	state.Printer = observability.NewPrinter(0)
	return state.Pop(request)
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
	assert.Equal(t, 9, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum) // never updated; see docs
}

func TestState_Pop_SummaryUpdatesTooLarge(t *testing.T) {
	state := &FileStreamState{MaxFileLineSize: 99, SummaryLineNum: 7}
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	state.Logger = logger
	request := &FileStreamRequest{}
	request.HistoryLines = []string{"the history"}
	request.SummaryUpdates = runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "key", ValueJson: `"value"`},
			{Key: "bad", ValueJson: "invalid"},
		},
	})

	json, hasMore := state.Pop(request)

	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)
	assert.False(t, request.SummaryUpdates.IsEmpty())
	assert.Equal(t, 15, state.LastRunSummarySize)
	assert.Equal(t, 7, state.SummaryLineNum)

	// History-only arrivals leave the already encoded summary valid.
	request.Merge(&FileStreamRequest{HistoryLines: []string{"more history"}})
	json, hasMore = state.Pop(request)
	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)

	json, hasMore = state.Pop(request)

	assert.False(t, hasMore)
	assert.Equal(t,
		[]string{`{"key":"value"}`},
		json.Files[SummaryFileName].Content)
	assert.Nil(t, request.SummaryUpdates)
	assert.Equal(t, 1, strings.Count(logs.String(), "error in path bad"))
}

func TestState_Pop_SummaryLineTooLong(t *testing.T) {
	state := &FileStreamState{MaxFileLineSize: 1, SummaryLineNum: 7}
	request := &FileStreamRequest{SummaryUpdates: summaryUpdate("a", "12")}
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	printer := observability.NewPrinter(100)

	state.Logger, state.Printer = logger, printer
	json, hasMore := state.Pop(request)

	assert.False(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)
	assert.Nil(t, request.SummaryUpdates)
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

func summaryUpdate(key, valueJSON string) *runsummary.Updates {
	return runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: key, ValueJson: valueJSON}},
	})
}

func popSummaryLine(
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
	require.Len(t, chunk.Content, 1)
	return chunk.Content[0], json.SummaryDelta
}

func deltaState() *FileStreamState {
	return &FileStreamState{
		SummaryDelta:        true,
		MaxFileLineSize:     999,
		MaxRequestSizeBytes: 999,
	}
}

func TestState_Pop_SummaryDelta(t *testing.T) {
	removeA := runsummary.FromProto(&spb.SummaryRecord{
		Remove: []*spb.SummaryItem{{Key: "a"}},
	})
	steps := []struct {
		name      string
		request   *FileStreamRequest
		want      string
		wantDelta bool
	}{
		{"changes are deltas",
			&FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")},
			`{"a":1}`, true},
		{"only what changed",
			&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")},
			`{"b":2}`, true},
		{"removal is full",
			&FileStreamRequest{SummaryUpdates: removeA},
			`{"b":2}`, false},
		{"deltas after removal",
			&FileStreamRequest{SummaryUpdates: summaryUpdate("c", "3")},
			`{"c":3}`, true},
		{"no change, no summary",
			&FileStreamRequest{EventsLines: []string{`{"cpu":1}`}},
			"", false},
		{"empty delta is skipped",
			&FileStreamRequest{SummaryUpdates: summaryUpdate("unset", "null")},
			"", false},
		{"finish checkpoints even with no pending updates",
			&FileStreamRequest{Complete: true},
			`{"b":2,"c":3}`, false},
	}
	state := deltaState()

	for _, step := range steps {
		line, isDelta := popSummaryLine(t, state, step.request)

		if step.want == "" {
			assert.Empty(t, line, step.name)
		} else {
			assert.JSONEq(t, step.want, line, step.name)
		}
		assert.Equal(t, step.wantDelta, isDelta, step.name)
	}
}

func TestState_Pop_FullSummaryWithoutDeltas(t *testing.T) {
	state := &FileStreamState{MaxFileLineSize: 999, MaxRequestSizeBytes: 999}
	popSummaryLine(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("a", "1")})

	line, isDelta := popSummaryLine(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})
	assert.JSONEq(t, `{"a":1,"b":2}`, line)
	assert.False(t, isDelta)

	line, _ = popSummaryLine(t, state, &FileStreamRequest{Complete: true})
	assert.Empty(t, line)
}

func TestState_Pop_FinalCheckpoint(t *testing.T) {
	const history = `{"acc":0.6}`
	const delta = `{"best":0.7}`
	const full = `{"acc":0.6,"best":0.7}`
	type chunk map[string]string
	for _, tc := range []struct {
		name                    string
		requestLimit, lineLimit int
		chunks                  []chunk
	}{
		{"shares last request", len(full) + len("done"), len(full), []chunk{
			{HistoryFileName: history, SummaryFileName: delta}, {OutputFileName: "done", SummaryFileName: full},
		}},
		{"waits for room", len(delta), len(full), []chunk{
			{HistoryFileName: history}, {SummaryFileName: delta}, {OutputFileName: "done"}, {SummaryFileName: full},
		}},
		{"checkpoint too large", len(delta), len(delta), []chunk{
			{HistoryFileName: history}, {SummaryFileName: delta}, {OutputFileName: "done"},
		}},
		{"delta already occupies summary line", 999, len(full), []chunk{
			{HistoryFileName: history, SummaryFileName: delta, OutputFileName: "done"}, {SummaryFileName: full},
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			logger, logs := observabilitytest.NewRecordingTestLogger(t)
			state := &FileStreamState{
				SummaryDelta:        true,
				Logger:              logger,
				Printer:             observability.NewPrinter(10),
				MaxRequestSizeBytes: tc.requestLimit,
				MaxFileLineSize:     tc.lineLimit,
			}
			request := &FileStreamRequest{
				HistoryLines: []string{history},
				SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
					Update: []*spb.SummaryItem{
						{Key: "acc", ValueJson: "0.6", FromHistory: true},
						{Key: "best", ValueJson: "0.7"},
					},
				}),
				ConsoleLines: &sparselist.SparseList[string]{},
				Complete:     true,
				ExitCode:     5,
			}
			request.ConsoleLines.Put(0, "done")

			for i, files := range tc.chunks {
				final := i == len(tc.chunks)-1
				json, more := state.Pop(request)
				require.Equal(t, !final, more)
				require.Len(t, json.Files, len(files))
				for file, wantLine := range files {
					lines := json.Files[file].Content
					require.Len(t, lines, 1, file)
					if file == SummaryFileName {
						assert.JSONEq(t, wantLine, lines[0])
					} else {
						assert.Equal(t, wantLine, lines[0])
					}
				}
				assert.Equal(t, files[SummaryFileName] == delta, json.SummaryDelta)
				if final {
					assert.Equal(t, new(true), json.Complete)
					assert.Equal(t, new(int32(5)), json.ExitCode)
				} else {
					assert.Nil(t, json.Complete)
				}
			}
			assert.Empty(t, state.Printer.Read())
			if tc.lineLimit < len(full) {
				assert.Contains(t, logs.String(), "run summary line too long")
			}
		})
	}
}

func TestState_Pop_SummaryDeltaThatDoesNotFitAccumulates(t *testing.T) {
	state := deltaState()
	state.MaxRequestSizeBytes = 10

	request := &FileStreamRequest{
		HistoryLines:   []string{"the history"},
		SummaryUpdates: summaryUpdate("b", "2"),
	}
	json, hasMore := pop(t, state, request)
	assert.True(t, hasMore)
	assert.NotContains(t, json.Files, SummaryFileName)

	request.Merge(&FileStreamRequest{SummaryUpdates: summaryUpdate("c", "3")})
	line, isDelta := popSummaryLine(t, state, request)
	assert.JSONEq(t, `{"b":2,"c":3}`, line)
	assert.True(t, isDelta)
}

func TestState_Pop_SummaryDeltaAfterTooLargeSummary(t *testing.T) {
	state := deltaState()
	state.MaxFileLineSize = 12

	line, _ := popSummaryLine(t, state, &FileStreamRequest{
		SummaryUpdates: summaryUpdate("big", `"a long value"`),
	})
	assert.Empty(t, line)

	line, isDelta := popSummaryLine(t, state,
		&FileStreamRequest{SummaryUpdates: summaryUpdate("b", "2")})
	assert.JSONEq(t, `{"b":2}`, line)
	assert.True(t, isDelta)
}
