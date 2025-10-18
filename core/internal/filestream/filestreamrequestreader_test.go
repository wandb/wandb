package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func testLogger(t *testing.T) *observability.CoreLogger {
	t.Helper()
	return observabilitytest.NewTestLogger(t)
}

func TestSizeLimit_HugeLine_SentAlone(t *testing.T) {
	reader, isTruncated := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"too large", "next"}},
		0,
	)

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))
	next, done := reader.Next()

	// Even though "too large" is above the size limit (0) we do want
	// to eventually send it. There are other guards elsewhere to avoid
	// this case and inform the user.
	assert.True(t, isTruncated)
	assert.Equal(t, []string{"too large"}, json.Files[HistoryFileName].Content)
	assert.Equal(t, []string{"next"}, next.HistoryLines)
	assert.False(t, done)
}

func TestSizeLimit_AboveMaxSize(t *testing.T) {
	reader, isTruncated := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"one", "two"}},
		// "one" will fit, "two" will not, and the size will not be exactly 5
		5,
	)

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))

	assert.True(t, isTruncated)
	assert.Equal(t, []string{"one"}, json.Files[HistoryFileName].Content)
}

func TestSizeLimit_BelowMaxSize(t *testing.T) {
	reader, isTruncated := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"one", "two"}},
		10, // both lines will fit
	)

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))

	assert.False(t, isTruncated)
	assert.Equal(t, []string{"one", "two"}, json.Files[HistoryFileName].Content)
}

func TestHistory_ReadFull(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{HistoryLines: []string{"one", "two"}}, 999)
	state := &FileStreamState{HistoryLineNum: 5}

	json := reader.GetJSON(state, testLogger(t))
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

	json := reader.GetJSON(state, testLogger(t))
	next, done := reader.Next()

	assert.Equal(t, 6, state.HistoryLineNum)
	assert.Equal(t, 5, json.Files[HistoryFileName].Offset)
	assert.Equal(t, []string{"one"}, json.Files[HistoryFileName].Content)
	assert.Equal(t, []string{"two"}, next.HistoryLines)
	assert.False(t, done)
}

func TestEvents_ReadFull(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{EventsLines: []string{"one", "two"}}, 999)
	state := &FileStreamState{EventsLineNum: 5}

	json := reader.GetJSON(state, testLogger(t))
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

	json := reader.GetJSON(state, testLogger(t))
	next, done := reader.Next()

	assert.Equal(t, 6, state.EventsLineNum)
	assert.Equal(t, 5, json.Files[EventsFileName].Offset)
	assert.Equal(t, []string{"one"}, json.Files[EventsFileName].Content)
	assert.Equal(t, []string{"two"}, next.EventsLines)
	assert.False(t, done)
}

func TestSummary_ReadNil(t *testing.T) {
	reader, _ := NewRequestReader(&FileStreamRequest{}, 99)
	state := NewFileStreamState()
	state.SummaryLineNum = 9

	json := reader.GetJSON(state, testLogger(t))
	next, _ := reader.Next()

	assert.Equal(t, 9, state.SummaryLineNum) // unchanged!
	assert.Empty(t, state.RunSummary.ToNestedMaps())
	assert.NotContains(t, json.Files, SummaryFileName)
	assert.Nil(t, next.SummaryUpdates)
}

func TestSummary_Read(t *testing.T) {
	reader, _ := NewRequestReader(&FileStreamRequest{
		SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{
				{Key: "test", ValueJson: `1`},
			},
		}),
	}, 99)
	state := NewFileStreamState()
	state.RunSummary = runsummary.New()
	state.RunSummary.Set(pathtree.PathOf("initial"), "value")
	state.SummaryLineNum = 9

	json := reader.GetJSON(state, testLogger(t))
	next, _ := reader.Next()

	assert.Equal(t, 9, state.SummaryLineNum) // unchanged!
	assert.Equal(t, map[string]any{
		"initial": "value",
		"test":    int64(1),
	}, state.RunSummary.ToNestedMaps())
	assert.Equal(t, 9, json.Files[SummaryFileName].Offset)
	assert.Len(t, json.Files[SummaryFileName].Content, 1)
	assert.JSONEq(t,
		`{"initial":"value","test":1}`,
		json.Files[SummaryFileName].Content[0])
	assert.Nil(t, next.SummaryUpdates)
}

func TestConsole_ReadFull(t *testing.T) {
	req := &FileStreamRequest{}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(1, "line 1")
	reader, _ := NewRequestReader(req, 999)
	state := &FileStreamState{ConsoleLineOffset: 1}

	json := reader.GetJSON(state, testLogger(t))
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

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))
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

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))
	next, done := reader.Next()

	assert.Equal(t, []string{"line 0"}, json.Files[OutputFileName].Content)
	assert.Equal(t, 1, next.ConsoleLines.Len())
	assert.Equal(t, "line 99", next.ConsoleLines.GetOrZero(99))
	assert.False(t, done)
}

func TestUploadedFiles_Read(t *testing.T) {
	reader, _ := NewRequestReader(&FileStreamRequest{
		UploadedFiles: map[string]struct{}{
			"file1": {},
			"file2": {},
		},
	}, 999)

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))
	next, _ := reader.Next()

	assert.Len(t, json.Uploaded, 2)
	assert.Contains(t, json.Uploaded, "file1")
	assert.Contains(t, json.Uploaded, "file2")
	assert.Empty(t, next.UploadedFiles)
}

func TestExitCode_Read_Done(t *testing.T) {
	reader, _ := NewRequestReader(
		&FileStreamRequest{Complete: true, ExitCode: 5}, 99)

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))

	assert.True(t, *json.Complete)
	assert.EqualValues(t, 5, *json.ExitCode)
}

func TestExitCode_Read_NotDone(t *testing.T) {
	// Non-consecutive console lines can't be sent in one request.
	req := &FileStreamRequest{Complete: true, ExitCode: 5}
	req.ConsoleLines.Put(0, "line 0")
	req.ConsoleLines.Put(9, "line 9")
	reader, _ := NewRequestReader(req, 99)

	json := reader.GetJSON(&FileStreamState{}, testLogger(t))

	assert.Nil(t, json.Complete)
	assert.Nil(t, json.ExitCode)
}
