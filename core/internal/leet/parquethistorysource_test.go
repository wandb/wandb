package leet

import (
	"context"
	"fmt"
	"io"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

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
		observability.NewNoOpLogger(),
	)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)

	batch, ok := msg.(ChunkedBatchMsg)
	require.True(t, ok)
	require.False(t, batch.HasMore)
	require.Len(t, batch.Msgs, 4)

	runMsg, ok := batch.Msgs[0].(RunMsg)
	require.True(t, ok)
	assert.Equal(t, "entity/project/run-id", runMsg.RunPath)
	assert.Equal(t, "run-id", runMsg.ID)
	assert.Equal(t, "project", runMsg.Project)
	assert.Equal(t, "run_display_name", runMsg.DisplayName)
	assert.Nil(t, runMsg.Config)

	summaryMsg, ok := batch.Msgs[1].(SummaryMsg)
	require.True(t, ok)
	require.Len(t, summaryMsg.Summary, 1)
	assert.Len(t, summaryMsg.Summary[0].Update, 2)

	historyMsg, ok := batch.Msgs[2].(HistoryMsg)
	require.True(t, ok)
	assert.Equal(t, "entity/project/run-id", historyMsg.RunPath)
	assert.Equal(t, []float64{0, 50, 1000}, historyMsg.Metrics["loss"].X)
	assert.Equal(t, []float64{1.0, 0.5, 0.1}, historyMsg.Metrics["loss"].Y)

	require.IsType(t, FileCompleteMsg{}, batch.Msgs[3])

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
		observability.NewNoOpLogger(),
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

func TestParquetHistorySource_Close(t *testing.T) {
	reader := &fakeStepReader{steps: []parquet.KeyValueList{lossRow(0, 1.0)}}
	source := newParquetHistorySource(
		t.Context(),
		testRunInfo(nil),
		reader,
		observability.NewNoOpLogger(),
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
					"displayName": "run_display_name",
					"summaryMetrics": %q
				}
			}
		}`, `{"_step":1000,"loss":0.1}`),
	)

	runInfo, err := loadRunInfo(t.Context(), mockGQL, "entity", "project", "run-id")
	require.NoError(t, err)

	assert.Equal(t, "entity", runInfo.entity)
	assert.Equal(t, "project", runInfo.project)
	assert.Equal(t, "run-id", runInfo.runId)
	assert.Equal(t, "run_display_name", runInfo.displayName)
	assert.Equal(t, int64(1000), maxStepFromSummary(runInfo.runSummary))
}

func TestLoadRunInfo_RunNotFound(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("QueryRunInfo"),
		`{"project": {"run": null}}`,
	)

	_, err := loadRunInfo(t.Context(), mockGQL, "entity", "project", "run-id")
	require.ErrorContains(t, err, `run "run-id" not found in entity/project`)
}
