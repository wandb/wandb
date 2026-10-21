package leet

import (
	"context"
	"fmt"
	"io"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
)

// fakeStepReader is an in-memory historyStepReader.
type fakeStepReader struct {
	steps    []parquet.KeyValueList
	released int
}

func (f *fakeStepReader) GetHistorySteps(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) ([]parquet.KeyValueList, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	var out []parquet.KeyValueList
	for _, step := range f.steps {
		if v := step.StepValue(); v >= minStep && v < maxStep {
			out = append(out, step)
		}
	}
	return out, nil
}

func (f *fakeStepReader) Release() { f.released++ }

func lossRow(step int64, loss float64) parquet.KeyValueList {
	return parquet.KeyValueList{
		{Key: parquet.StepKey, Value: step},
		{Key: "loss", Value: loss},
	}
}

func testRunInfo(runSummary map[string]any) *RunInfo {
	return &RunInfo{
		entity:      "entity",
		project:     "project",
		runId:       "run-id",
		runSummary:  runSummary,
		displayName: "run_display_name",
		runState:    RunStateFinished,
	}
}

func TestParquetHistorySource_Read(t *testing.T) {
	reader := &fakeStepReader{
		steps: []parquet.KeyValueList{
			lossRow(0, 1.0),
			lossRow(50, 0.5),
			lossRow(1000, 0.1),
		},
	}
	source := newParquetHistorySource(
		t.Context(),
		testRunInfo(map[string]any{"_step": int64(1000), "loss": 0.1}),
		reader,
		&fakeStepReader{},
		observability.NewNoOpLogger(),
		nil,
	)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)

	batch, ok := msg.(ChunkedBatchMsg)
	require.True(t, ok)
	require.False(t, batch.HasMore)
	require.Len(t, batch.Msgs, 3)

	runMsg, ok := batch.Msgs[0].(RunMsg)
	require.True(t, ok)
	assert.Equal(t, "entity/project/run-id", runMsg.RunPath)
	assert.Equal(t, "run-id", runMsg.ID)
	assert.Equal(t, "project", runMsg.Project)
	assert.Equal(t, "run_display_name", runMsg.DisplayName)
	assert.Nil(t, runMsg.Config)
	assert.Equal(t, RunStateFinished, *runMsg.State)

	summaryMsg, ok := batch.Msgs[1].(SummaryMsg)
	require.True(t, ok)
	require.Len(t, summaryMsg.Summary, 1)
	assert.Len(t, summaryMsg.Summary[0].Update, 2)

	historyMsg, ok := batch.Msgs[2].(HistoryMsg)
	require.True(t, ok)
	assert.Equal(t, "entity/project/run-id", historyMsg.RunPath)
	assert.Equal(t, []float64{0, 50, 1000}, historyMsg.Metrics["loss"].X)
	assert.Equal(t, []float64{1.0, 0.5, 0.1}, historyMsg.Metrics["loss"].Y)

	// The source is exhausted.
	_, err = source.Read(100, 10*time.Second)
	require.ErrorIs(t, err, io.EOF)
}

func TestParquetHistorySource_Read_WithoutSummaryStepStopsAtEmptyWindow(t *testing.T) {
	reader := &fakeStepReader{
		steps: []parquet.KeyValueList{
			lossRow(0, 1.0),
			lossRow(99, 0.1),
		},
	}
	source := newParquetHistorySource(
		t.Context(),
		testRunInfo(map[string]any{"loss": 0.1}), // no "_step" bound
		reader,
		&fakeStepReader{},
		observability.NewNoOpLogger(),
		nil,
	)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)

	batch, ok := msg.(ChunkedBatchMsg)
	require.True(t, ok)
	require.False(t, batch.HasMore)

	historyMsg, ok := batch.Msgs[2].(HistoryMsg)
	require.True(t, ok)
	assert.Equal(t, []float64{0, 99}, historyMsg.Metrics["loss"].X)
	assert.Equal(t, []float64{1.0, 0.1}, historyMsg.Metrics["loss"].Y)
}

func runInfoResponse(state, summary string) string {
	return fmt.Sprintf(`{
		"project": {
			"run": {"name": "run-id", "state": %q, "summaryMetrics": %q}
		}
	}`, state, summary)
}

func TestParquetHistorySource_LiveRun(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		runInfoResponse("finished", `{"_step":1}`),
	)
	runInfo := testRunInfo(map[string]any{"_step": int64(0)})
	runInfo.runState = RunStateRunning
	source := newParquetHistorySource(
		t.Context(),
		runInfo,
		&fakeStepReader{steps: []parquet.KeyValueList{lossRow(0, 1.0)}},
		&fakeStepReader{steps: []parquet.KeyValueList{lossRow(1, 0.8)}},
		observability.NewNoOpLogger(),
		mockGQL,
	)
	readCmd := func() tea.Msg { return nil }

	// The first read loads the history up to the summary's step.
	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch := msg.(ChunkedBatchMsg)
	require.False(t, batch.HasMore)
	assert.Equal(t, []float64{0}, batch.Msgs[2].(HistoryMsg).Metrics["loss"].X)
	require.NotNil(t, source.NextLiveReadCmd(readCmd, false))

	// Polling picks up new history along with the current state and summary.
	msg, err = source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch = msg.(ChunkedBatchMsg)
	require.Len(t, batch.Msgs, 3)
	assert.Equal(t, RunStateFinished, *batch.Msgs[0].(RunMsg).State)
	assert.Equal(t, "1", batch.Msgs[1].(SummaryMsg).Summary[0].Update[0].ValueJson)
	assert.Equal(t, []float64{1}, batch.Msgs[2].(HistoryMsg).Metrics["loss"].X)
	require.Nil(t, source.NextLiveReadCmd(readCmd, false))
}

// A live run opened before it logged any history keeps polling the backend
// for its state.
func TestParquetHistorySource_LiveRunWithoutHistoryRefreshes(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		runInfoResponse("crashed", `{}`),
	)
	runInfo := testRunInfo(map[string]any{})
	runInfo.runState = RunStateRunning
	source := newParquetHistorySource(
		t.Context(),
		runInfo,
		&fakeStepReader{},
		&fakeStepReader{},
		observability.NewNoOpLogger(),
		mockGQL,
	)
	readCmd := func() tea.Msg { return nil }

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch := msg.(ChunkedBatchMsg)
	require.False(t, batch.HasMore)
	require.Len(t, batch.Msgs, 2)
	require.NotNil(t, source.NextLiveReadCmd(readCmd, false))

	msg, err = source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch = msg.(ChunkedBatchMsg)
	require.Len(t, batch.Msgs, 2)
	assert.Equal(t, RunStateCrashed, *batch.Msgs[0].(RunMsg).State)
	require.Nil(t, source.NextLiveReadCmd(readCmd, false))
}

// A live run that logs sparse steps must not stall on an empty window
// below the step its summary reports.
func TestParquetHistorySource_LiveRunSkipsStepGaps(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		runInfoResponse("running", `{"_step":250}`),
	)
	runInfo := testRunInfo(map[string]any{"_step": int64(0)})
	runInfo.runState = RunStateRunning
	source := newParquetHistorySource(
		t.Context(),
		runInfo,
		&fakeStepReader{steps: []parquet.KeyValueList{lossRow(0, 1.0)}},
		&fakeStepReader{steps: []parquet.KeyValueList{lossRow(250, 0.5)}},
		observability.NewNoOpLogger(),
		mockGQL,
	)
	_, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch := msg.(ChunkedBatchMsg)
	require.Len(t, batch.Msgs, 3)
	assert.Equal(t, []float64{250}, batch.Msgs[2].(HistoryMsg).Metrics["loss"].X)
}

func TestParquetHistorySource_Read_SystemMetrics(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunBucketedHistory"),
		`{"project":{"run":{"bucketedHistory":[[
			{"_timestampAvg":1700000000.4,"bucketSize":3,
			 "system/cpuAvg":42,"system/cpuMin":40,"system/gpu.0.gpuAvg":7},
			{"_timestampAvg":1700000060,"system/cpuAvg":55,"system/cpuHasNaN":false}
		]]}}}`,
	)
	runInfo := testRunInfo(map[string]any{"_step": int64(0)})
	runInfo.systemMetrics = map[string]any{
		"system.gpu.0.gpu":  int64(3),
		"system.cpu":        0.5,
		"system.gpu.0.name": "H100",
		"_runtime":          12.5,
	}
	source := newParquetHistorySource(
		t.Context(),
		runInfo,
		&fakeStepReader{steps: []parquet.KeyValueList{lossRow(0, 1.0)}},
		&fakeStepReader{},
		observability.NewNoOpLogger(),
		mockGQL,
	)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)

	batch := msg.(ChunkedBatchMsg)
	require.False(t, batch.HasMore)
	require.Len(t, batch.Msgs, 5)
	assert.Equal(t, StatsMsg{
		RunPath:   "entity/project/run-id",
		Timestamp: 1700000000,
		Metrics:   map[string]float64{"cpu": 42, "gpu.0.gpu": 7},
	}, batch.Msgs[3])
	assert.Equal(t, StatsMsg{
		RunPath:   "entity/project/run-id",
		Timestamp: 1700000060,
		Metrics:   map[string]float64{"cpu": 55},
	}, batch.Msgs[4])

	requests := mockGQL.AllRequests()
	require.Len(t, requests, 1)
	gqlmock.AssertVariables(t, requests[0], gqlmock.GQLVar("specs", gomock.Eq([]any{
		`{"bins":500,"keys":["system/cpu","system/gpu.0.gpu"],"xAxis":"_timestamp"}`,
	})))
}

// A live run's poll fetches the system metrics logged since the last
// sample, which the inclusive bound returns again and the source drops.
func TestParquetHistorySource_LiveRun_SystemMetrics(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunBucketedHistory"),
		`{"project":{"run":{"bucketedHistory":[[
			{"_timestampAvg":100,"_timestampLast":100,"system/cpuAvg":1},
			{"_timestampAvg":110.5,"_timestampLast":111,"system/cpuAvg":2}
		]]}}}`,
	)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		`{"project":{"run":{"name":"run-id","state":"running",
			"summaryMetrics":"{\"_step\":0}","systemMetrics":"{\"system.cpu\":3}"}}}`,
	)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunBucketedHistory"),
		`{"project":{"run":{"bucketedHistory":[[
			{"_timestampAvg":111,"_timestampLast":111,"system/cpuAvg":2},
			{"_timestampAvg":120,"_timestampLast":120,"system/cpuAvg":3}
		]]}}}`,
	)
	runInfo := testRunInfo(map[string]any{"_step": int64(0)})
	runInfo.runState = RunStateRunning
	runInfo.systemMetrics = map[string]any{"system.cpu": 1.0}
	source := newParquetHistorySource(
		t.Context(),
		runInfo,
		&fakeStepReader{steps: []parquet.KeyValueList{lossRow(0, 1.0)}},
		&fakeStepReader{},
		observability.NewNoOpLogger(),
		mockGQL,
	)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch := msg.(ChunkedBatchMsg)
	require.Len(t, batch.Msgs, 5)
	assert.Equal(t, int64(110), batch.Msgs[4].(StatsMsg).Timestamp)

	msg, err = source.Read(100, 10*time.Second)
	require.NoError(t, err)
	batch = msg.(ChunkedBatchMsg)
	require.Len(t, batch.Msgs, 3)
	assert.Equal(t, StatsMsg{
		RunPath:   "entity/project/run-id",
		Timestamp: 120,
		Metrics:   map[string]float64{"cpu": 3},
	}, batch.Msgs[2])

	requests := mockGQL.AllRequests()
	gqlmock.AssertVariables(t, requests[len(requests)-1], gqlmock.GQLVar("specs", gomock.Eq([]any{
		`{"bins":500,"keys":["system/cpu"],"minX":111,"xAxis":"_timestamp"}`,
	})))
}

func TestParquetHistorySource_Close(t *testing.T) {
	reader := &fakeStepReader{steps: []parquet.KeyValueList{lossRow(0, 1.0)}}
	source := newParquetHistorySource(
		t.Context(),
		testRunInfo(nil),
		reader,
		&fakeStepReader{},
		observability.NewNoOpLogger(),
		nil,
	)

	source.Close()
	source.Close()
	assert.Equal(t, 1, reader.released)

	_, err := source.Read(100, 10*time.Second)
	require.ErrorIs(t, err, io.EOF)
}

func TestParseParquetHistorySteps(t *testing.T) {
	logger := observability.NewNoOpLogger()
	historySteps := []parquet.KeyValueList{
		{
			{Key: parquet.StepKey, Value: float64(0)},
			{Key: "loss", Value: float64(1.0)},
			{Key: parquet.TimestampKey, Value: float64(100)},
		},
		{
			{Key: parquet.StepKey, Value: float64(1)},
			{Key: "loss", Value: float64(0.8)},
			{Key: "_runtime", Value: float64(3.2)},
		},
		{
			{Key: parquet.StepKey, Value: float64(2)},
			{Key: "loss", Value: float64(0.6)},
			{Key: "tokens", Value: uint64(42)},
		},
	}

	result := parseParquetHistorySteps(historySteps, logger)

	require.NotNil(t, result.Metrics)
	assert.Len(t, result.Metrics, 2)
	assert.Equal(t, []float64{0, 1, 2}, result.Metrics["loss"].X)
	assert.Equal(t, []float64{1.0, 0.8, 0.6}, result.Metrics["loss"].Y)
	assert.Equal(t, []float64{2}, result.Metrics["tokens"].X)
	assert.Equal(t, []float64{42}, result.Metrics["tokens"].Y)
}

func TestLoadRunInfo(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		fmt.Sprintf(`{
			"project": {
				"run": {
					"name": "run-id",
					"displayName": "run_display_name",
					"summaryMetrics": %q,
					"systemMetrics": %q
				}
			}
		}`, `{"_step":1000,"loss":0.1}`, `{"system.cpu":12.5}`),
	)

	runInfo, err := loadRunInfo(
		t.Context(), mockGQL, "entity", "project", "run-id", observability.NewNoOpLogger())
	require.NoError(t, err)

	assert.Equal(t, "entity", runInfo.entity)
	assert.Equal(t, "project", runInfo.project)
	assert.Equal(t, "run-id", runInfo.runId)
	assert.Equal(t, "run_display_name", runInfo.displayName)
	assert.Equal(t, int64(1000), maxStepFromSummary(runInfo.runSummary))
	assert.Equal(t, map[string]any{"system.cpu": 12.5}, runInfo.systemMetrics)
}

func TestLoadRunInfo_RunNotFound(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		`{"project": {"run": null}}`,
	)

	_, err := loadRunInfo(
		t.Context(), mockGQL, "entity", "project", "run-id", observability.NewNoOpLogger())
	require.ErrorContains(t, err, `run "run-id" not found in entity/project`)
}
