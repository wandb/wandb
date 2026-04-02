// The parquettest package uses unsafe pointer manipulation to mock the Rust
// FFI layer and is excluded from race-detector builds. This file imports it,
// so it must carry the same constraint.

//go:build !race

package leet_test

import (
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquettest"
)

func TestParseParquetHistorySteps(t *testing.T) {
	logger := observability.NewNoOpLogger()
	historySteps := []parquet.KeyValueList{
		{
			{Key: parquet.StepKey, Value: float64(0)},
			{Key: "loss", Value: float64(1.0)},
		},
		{
			{Key: parquet.StepKey, Value: float64(1)},
			{Key: "loss", Value: float64(0.8)},
		},
		{
			{Key: parquet.StepKey, Value: float64(2)},
			{Key: "loss", Value: float64(0.6)},
		},
	}

	result := leet.ParseParquetHistorySteps(historySteps, logger)

	require.NotNil(t, result)
	require.NotNil(t, result.Metrics)
	assert.Len(t, result.Metrics, 1)
	assert.Contains(t, result.Metrics, "loss")
	assert.Equal(t, []float64{0, 1, 2}, result.Metrics["loss"].X)
	assert.Equal(t, []float64{1.0, 0.8, 0.6}, result.Metrics["loss"].Y)
}

func TestReadRecords_ThenExit(t *testing.T) {
	logger := observability.NewNoOpLogger()
	t.Setenv("WANDB_CACHE_DIR", t.TempDir())

	columns := []parquettest.ColumnDef{
		{Name: "_step", ColType: "int64"},
		{Name: "loss", ColType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "loss": 1.0},
		{"_step": int64(1), "loss": 0.8},
		{"_step": int64(2), "loss": 0.6},
	}
	mockWrapper := parquettest.CreateMockRustArrowWrapper(
		t, columns, map[uintptr][]map[string]any{1: data},
	)

	dummyContent := parquettest.DummyFileContent()
	server := parquettest.CreateHTTPServer(
		t, parquettest.RespondWithContent(t, dummyContent),
	)
	mockGQL := parquettest.MockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)

	runInfo := leet.NewRunInfo(
		"entity",
		"project",
		"run-id",
		map[string]any{
			"loss": 0.6,
		},
		"run_display_name",
	)
	source, err := leet.NewParquetHistorySource(
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		mockWrapper,
		runInfo,
		logger,
	)
	require.NoError(t, err)

	msg, err := source.Read(100, 10*time.Second)
	require.NoError(t, err)
	require.NotNil(t, msg)
	assert.IsType(t, leet.ChunkedBatchMsg{}, msg)
	chunkedBatchMsg := msg.(leet.ChunkedBatchMsg)
	require.NotNil(t, chunkedBatchMsg.Msgs)
	assert.Len(t, chunkedBatchMsg.Msgs, 4)

	assert.IsType(t, leet.RunMsg{}, chunkedBatchMsg.Msgs[0])
	runMsg := chunkedBatchMsg.Msgs[0].(leet.RunMsg)
	assert.Equal(t, "run-id", runMsg.ID)
	assert.Equal(t, "project", runMsg.Project)
	assert.Equal(t, "run_display_name", runMsg.DisplayName)
	assert.Nil(t, runMsg.Config)

	assert.IsType(t, leet.SummaryMsg{}, chunkedBatchMsg.Msgs[1])
	summaryMsg := chunkedBatchMsg.Msgs[1].(leet.SummaryMsg)
	assert.NotNil(t, summaryMsg.Summary)
	assert.Len(t, summaryMsg.Summary, 1)
	assert.Equal(t, "loss", summaryMsg.Summary[0].Update[0].Key)
	assert.Equal(t, "0.6", summaryMsg.Summary[0].Update[0].ValueJson)

	assert.IsType(t, leet.HistoryMsg{}, chunkedBatchMsg.Msgs[2])
	historyMsg := chunkedBatchMsg.Msgs[2].(leet.HistoryMsg)
	assert.Contains(t, historyMsg.Metrics, "loss")
	assert.Equal(t, []float64{0, 1, 2}, historyMsg.Metrics["loss"].X)
	assert.Equal(t, []float64{1.0, 0.8, 0.6}, historyMsg.Metrics["loss"].Y)

	assert.IsType(t, leet.FileCompleteMsg{}, chunkedBatchMsg.Msgs[3])
	fileCompleteMsg := chunkedBatchMsg.Msgs[3].(leet.FileCompleteMsg)
	assert.Equal(t, int32(0), fileCompleteMsg.ExitCode)
}
