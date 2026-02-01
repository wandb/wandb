package leet_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator/iteratortest"
)

func mockGraphQLWithParquetUrls(urls []string) *gqlmock.MockClient {
	mockGQL := gqlmock.NewMockClient()
	urlsJsonBytes, _ := json.Marshal(urls)
	urlsJsonString := string(urlsJsonBytes)

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": `+urlsJsonString+`
					}
				}
			}
		}`,
	)

	return mockGQL
}

func serveParquetFile(t *testing.T, path string) *httptest.Server {
	t.Helper()

	parquetContent, err := os.ReadFile(path)
	require.NoError(t, err)

	handler := func(responseWriter http.ResponseWriter, request *http.Request) {
		responseWriter.Header().Set("Accept-Ranges", "bytes")

		// Handle range requests for remote reading
		rangeHeader := request.Header.Get("Range")
		if rangeHeader == "" {
			// Serve the entire file if no range request
			_, err := responseWriter.Write(parquetContent)
			require.NoError(t, err)
			return
		}

		var start, end int64
		_, err := fmt.Sscanf(rangeHeader, "bytes=%d-%d", &start, &end)
		require.NoError(t, err)

		responseWriter.Header().Set(
			"Content-Range",
			fmt.Sprintf("bytes %d-%d/%d", start, end, len(parquetContent)),
		)
		responseWriter.WriteHeader(http.StatusPartialContent)

		minLength := min(end+1, int64(len(parquetContent)))
		_, err = responseWriter.Write(parquetContent[start:minLength])
		require.NoError(t, err)
	}

	server := httptest.NewServer(http.HandlerFunc(handler))
	t.Cleanup(server.Close)

	return server
}

func TestParseParquetHistorySteps(t *testing.T) {
	logger := observability.NewNoOpLogger()
	historySteps := []iterator.KeyValueList{
		{
			{Key: iterator.StepKey, Value: float64(0)},
			{Key: "loss", Value: float64(1.0)},
		},
		{
			{Key: iterator.StepKey, Value: float64(1)},
			{Key: "loss", Value: float64(0.8)},
		},
		{
			{Key: iterator.StepKey, Value: float64(2)},
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
	path := filepath.Join(t.TempDir(), "test.parquet")
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "loss", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": int64(0), "loss": 1.0},
		{"_step": int64(1), "loss": 0.8},
		{"_step": int64(2), "loss": 0.6},
	}
	iteratortest.CreateTestParquetFileFromData(t, path, schema, data)
	server := serveParquetFile(t, path)
	mockGQL := mockGraphQLWithParquetUrls([]string{server.URL + "/test.parquet"})
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
