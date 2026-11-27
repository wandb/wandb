package filestream

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/filestream/metricsbatch"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sparselist"
)

func TestTypedHistoryReservation(t *testing.T) {
	for _, tc := range []struct {
		requestBytes int
		historyBytes int
	}{
		{defaultMaxRequestSizeBytes, 8 << 20},
		{15<<20 + 3, 12<<20 + 2},
	} {
		state := &FileStreamState{MaxRequestSizeBytes: tc.requestBytes}
		buffer := &FileStreamRequest{}
		state.merge(buffer, typedHistoryUpdate(&metricsbatch.Row{}))
		require.Equal(t, tc.historyBytes, buffer.typedHistory.maxHistoryBytes)
		require.False(t, state.IsAtSizeLimit(buffer))
	}
}

func TestTypedHistoryPopSharesBudget(t *testing.T) {
	state := &FileStreamState{
		MaxRequestSizeBytes: 120,
		MaxFileLineSize:     120,
		HistoryLineNum:      127,
		EventsLineNum:       12,
		UnsentSummary:       "{}",
		LastRunSummarySize:  2,
	}
	buffer := &FileStreamRequest{Complete: true, ExitCode: 7}
	state.merge(buffer, typedHistoryUpdate(
		&metricsbatch.Row{},
		historyRow(t, 123, "metric", "value"),
	))
	buffer.ConsoleLines = &sparselist.SparseList[string]{}
	buffer.ConsoleLines.Put(2, "a")
	buffer.ConsoleLines.Put(3, "b")
	historyBytes := buffer.typedHistory.openBudgetBytes()
	event := strings.Repeat("e", state.MaxRequestSizeBytes-historyBytes-3)
	buffer.EventsLines = []string{event}

	require.True(t, state.IsAtSizeLimit(buffer))
	first, more := popTypedHistoryForTest(state, buffer)
	require.True(t, more)
	require.Nil(t, first.Complete)
	require.NotContains(t, first.Files, HistoryFileName)
	require.Equal(t, OffsetAndContent{Offset: 12, Content: []string{event}},
		first.Files[EventsFileName])
	require.Equal(t, []string{"{}"}, first.Files[SummaryFileName].Content)
	require.Equal(t, OffsetAndContent{Offset: 2, Content: []string{"a"}},
		first.Files[OutputFileName])
	require.EqualValues(t, 127, first.TypedHistory.Offset)
	require.EqualValues(t, 2, first.TypedHistory.RowCount)
	require.Equal(t, []bool{false, true}, first.TypedHistory.Batch.HasSeq)
	require.Equal(t, 129, state.HistoryLineNum)
	require.Less(t, proto.Size(&filestreamv1.FileStreamUpload{History: first.TypedHistory}),
		historyBytes)

	last, more := popTypedHistoryForTest(state, buffer)
	require.False(t, more)
	require.Nil(t, last.TypedHistory)
	require.Equal(t, OffsetAndContent{Offset: 3, Content: []string{"b"}},
		last.Files[OutputFileName])
	require.NotNil(t, last.Complete)
	require.True(t, *last.Complete)
	require.NotNil(t, last.ExitCode)
	require.EqualValues(t, 7, *last.ExitCode)
	require.Equal(t, 129, state.HistoryLineNum)
}

func TestTypedHistoryPopOversizedAndSeparateFromJSONL(t *testing.T) {
	state := &FileStreamState{MaxRequestSizeBytes: 100, HistoryLineNum: 5}
	buffer := &FileStreamRequest{
		HistoryLines: []string{"legacy"},
		EventsLines:  []string{"event"},
	}
	state.merge(buffer, typedHistoryUpdate(
		historyRow(t, 1, "small", "first"),
		historyRow(t, 2, "large", strings.Repeat("x", state.MaxRequestSizeBytes)),
	))
	require.True(t, state.IsAtSizeLimit(buffer))

	first, more := popTypedHistoryForTest(state, buffer)
	require.True(t, more)
	require.NotContains(t, first.Files, HistoryFileName)
	require.EqualValues(t, 5, first.TypedHistory.Offset)
	require.EqualValues(t, 1, first.TypedHistory.RowCount)
	require.Equal(t, []int64{1}, first.TypedHistory.Batch.Seqs)

	buffer.EventsLines = []string{"after oversized"}
	second, more := popTypedHistoryForTest(state, buffer)
	require.True(t, more)
	require.Empty(t, second.Files)
	require.EqualValues(t, 6, second.TypedHistory.Offset)
	require.EqualValues(t, 1, second.TypedHistory.RowCount)
	require.Equal(t, []int64{2}, second.TypedHistory.Batch.Seqs)
	require.False(t, second.IsHeartbeat())
	wire, err := json.Marshal(second)
	require.NoError(t, err)
	require.JSONEq(t, `{}`, string(wire))

	third, more := popTypedHistoryForTest(state, buffer)
	require.False(t, more)
	require.Nil(t, third.TypedHistory)
	require.Equal(t, OffsetAndContent{Offset: 7, Content: []string{"legacy"}},
		third.Files[HistoryFileName])
	require.Equal(t, []string{"after oversized"}, third.Files[EventsFileName].Content)
	require.Equal(t, 8, state.HistoryLineNum)
}

func TestCollectLoopTypedHistoryFlush(t *testing.T) {
	for _, flush := range []string{"input close", "preemption", "sealed backlog"} {
		t.Run(flush, func(t *testing.T) {
			limiter := rate.NewLimiter(rate.Every(time.Hour), 1)
			require.True(t, limiter.Allow())
			loop := CollectLoop{
				Logger:            observability.NewNoOpLogger(),
				Printer:           observability.NewPrinter(0),
				TransmitRateLimit: limiter,
			}
			requests := make(chan *FileStreamRequest, 2)
			requests <- typedHistoryUpdate(historyRow(t, 1, "small", "first"))
			switch flush {
			case "input close":
				close(requests)
			case "preemption":
				requests <- &FileStreamRequest{Preempting: true}
			case "sealed backlog":
				requests <- typedHistoryUpdate(historyRow(t, 2, "large", strings.Repeat("x", 100)))
			}
			output := loop.Start(&FileStreamState{MaxRequestSizeBytes: 100}, requests)
			defer output.IgnoreFutureRequests()
			if flush != "input close" {
				defer close(requests)
			}

			first, ok := output.NextRequest(time.After(5 * time.Second))
			require.True(t, ok)
			require.NotNil(t, first.TypedHistory)
			require.Equal(t, []int64{1}, first.TypedHistory.Batch.Seqs)
			if flush == "preemption" {
				require.NotNil(t, first.Preempting)
				require.True(t, *first.Preempting)
			}
			if flush == "sealed backlog" {
				second, ok := output.NextRequest(time.After(5 * time.Second))
				require.True(t, ok)
				require.NotNil(t, second.TypedHistory)
				require.EqualValues(t, 1, second.TypedHistory.Offset)
				require.Equal(t, []int64{2}, second.TypedHistory.Batch.Seqs)
			}
		})
	}
}

func typedHistoryUpdate(rows ...*metricsbatch.Row) *FileStreamRequest {
	return &FileStreamRequest{typedHistoryRows: rows}
}

func popTypedHistoryForTest(
	state *FileStreamState,
	buffer *FileStreamRequest,
) (*FileStreamRequestJSON, bool) {
	return state.Pop(buffer, observability.NewNoOpLogger(), observability.NewPrinter(0))
}
