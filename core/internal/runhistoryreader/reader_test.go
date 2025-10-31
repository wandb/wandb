package runhistoryreader

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator/iteratortest"
)

func respondWithParquetContent(
	t *testing.T,
	parquetContent []byte,
) func(responseWriter http.ResponseWriter, request *http.Request) {
	t.Helper()

	return func(responseWriter http.ResponseWriter, request *http.Request) {
		responseWriter.Header().Set("Accept-Ranges", "bytes")

		// Handle range requests for remote reading
		rangeHeader := request.Header.Get("Range")
		if rangeHeader == "" {
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

		pqLen := int64(len(parquetContent))
		min := slices.Min([]int64{end+1, pqLen})
		_, err = responseWriter.Write(parquetContent[start:min])
		require.NoError(t, err)
	}
}

func createHttpServer(
	t *testing.T,
	writerFunc func(responseWriter http.ResponseWriter, request *http.Request),
) *httptest.Server {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(writerFunc))
	t.Cleanup(server.Close)

	return server
}

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

func TestHistoryReader_GetHistorySteps_WithoutKeys(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "metric1", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
		{"_step": int64(1), "metric1": 2.0},
		{"_step": int64(2), "metric1": 3.0},
	}
	parquetFilePath := filepath.Join(tempDir, "test.parquet")
	iteratortest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
	parquetContent, err := os.ReadFile(parquetFilePath)
	require.NoError(t, err)
	server := createHttpServer(t, respondWithParquetContent(t, parquetContent))
	mockGQL := mockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)
	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		http.DefaultClient,
		[]string{},
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 3)
	expectedResults := []iterator.KeyValueList{
		{
			{Key: "_step", Value: int64(0)},
			{Key: "metric1", Value: 1.0},
		},
		{
			{Key: "_step", Value: int64(1)},
			{Key: "metric1", Value: 2.0},
		},
		{
			{Key: "_step", Value: int64(2)},
			{Key: "metric1", Value: 3.0},
		},
	}
	for i, result := range results {
		assert.ElementsMatch(t, expectedResults[i], result)
	}
}

func TestHistoryReader_GetHistorySteps_MultipleFiles(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "metric1", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data1 := []map[string]any{
		{"_step": int64(0), "metric1": 0.0},
		{"_step": int64(1), "metric1": 1.0},
	}
	data2 := []map[string]any{
		{"_step": int64(3), "metric1": 3.0},
		{"_step": int64(4), "metric1": 4.0},
	}
	servers := make([]*httptest.Server, 2)
	for i, data := range [][]map[string]any{data1, data2} {
		parquetFilePath := filepath.Join(tempDir, fmt.Sprintf("test%d.parquet", i))
		iteratortest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
		parquetContent, err := os.ReadFile(parquetFilePath)
		require.NoError(t, err)
		servers[i] = createHttpServer(
			t,
			respondWithParquetContent(t, parquetContent),
		)
	}
	mockGQL := mockGraphQLWithParquetUrls([]string{
		servers[0].URL + "/test1.parquet",
		servers[1].URL + "/test2.parquet",
	})
	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		http.DefaultClient,
		[]string{},
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 1, 4)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	expectedResults := []iterator.KeyValueList{
		{
			{Key: "_step", Value: int64(1)},
			{Key: "metric1", Value: 1.0},
		},
		{
			{Key: "_step", Value: int64(3)},
			{Key: "metric1", Value: 3.0},
		},
	}
	for i, result := range results {
		assert.ElementsMatch(t, expectedResults[i], result)
	}
}

func TestHistoryReader_GetHistorySteps_WithKeys(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "metric1", Type: arrow.PrimitiveTypes.Float64},
			{Name: "metric2", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0, "metric2": 10.0},
		{"_step": int64(1), "metric1": 2.0, "metric2": 20.0},
		{"_step": int64(2), "metric1": 3.0, "metric2": 30.0},
	}
	parquetFilePath := filepath.Join(tempDir, "test.parquet")
	iteratortest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
	parquetContent, err := os.ReadFile(parquetFilePath)
	require.NoError(t, err)
	server := createHttpServer(t, respondWithParquetContent(t, parquetContent))
	mockGQL := mockGraphQLWithParquetUrls([]string{
		server.URL + "/test.parquet",
	})
	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		http.DefaultClient,
		[]string{"metric1"},
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 3)
	expectedResults := []iterator.KeyValueList{
		{
			{Key: "_step", Value: int64(0)},
			{Key: "metric1", Value: 1.0},
		},
		{
			{Key: "_step", Value: int64(1)},
			{Key: "metric1", Value: 2.0},
		},
		{
			{Key: "_step", Value: int64(2)},
			{Key: "metric1", Value: 3.0},
		},
	}
	for i, result := range results {
		assert.ElementsMatch(t, expectedResults[i], result)
	}
}
