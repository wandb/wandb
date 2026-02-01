package runhistoryreader

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/hashicorp/go-retryablehttp"
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

		minLength := min(end+1, int64(len(parquetContent)))
		_, err = responseWriter.Write(parquetContent[start:minLength])
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
	t.Setenv("WANDB_CACHE_DIR", tempDir)

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
		retryablehttp.NewClient(),
		[]string{},
		true,
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
	os.Setenv("WANDB_CACHE_DIR", tempDir)
	defer os.Unsetenv("WANDB_CACHE_DIR")

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
		retryablehttp.NewClient(),
		[]string{},
		true,
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
		assert.ElementsMatch(t, expectedResults[i], result, "Result %d doesn't match expected", i)
	}
}

func TestHistoryReader_GetHistorySteps_WithKeys(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()
	t.Setenv("WANDB_CACHE_DIR", tempDir)

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
		retryablehttp.NewClient(),
		[]string{"metric1"},
		true,
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

func TestHistoryReader_GetHistorySteps_AllLiveData(t *testing.T) {
	ctx := t.Context()
	mockGQL := gqlmock.NewMockClient()

	// Mock RunParquetHistory with no parquet files, only live data
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": [],
						"liveData": [
							{"_step": 0},
							{"_step": 1}
						]
					}
				}
			}
		}`,
	)

	// Mock HistoryPage for the live data request (no keys specified)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("HistoryPage"),
		`{
			"project": {
				"run": {
					"history": [
						"{\"_step\":0,\"metric1\":1.0}",
						"{\"_step\":1,\"metric1\":2.0}"
					]
				}
			}
		}`,
	)

	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{},
		true,
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	assert.ElementsMatch(t, results[0], iterator.KeyValueList{
		{Key: "_step", Value: int64(0)},
		{Key: "metric1", Value: 1.0},
	})
	assert.ElementsMatch(t, results[1], iterator.KeyValueList{
		{Key: "_step", Value: int64(1)},
		{Key: "metric1", Value: 2.0},
	})
}

func TestHistoryReader_GetHistorySteps_AllLiveData_WithKeys(t *testing.T) {
	ctx := t.Context()
	mockGQL := gqlmock.NewMockClient()

	// Mock RunParquetHistory with no parquet files, only live data
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": [],
						"liveData": [
							{"_step": 0},
							{"_step": 1}
						]
					}
				}
			}
		}`,
	)

	// Mock SampledHistoryPage for the live data request with specific keys
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("SampledHistoryPage"),
		`{
			"project": {
				"run": {
					"sampledHistory": [
						[
							{"_step":0,"metric1":1.0},
							{"_step":1,"metric1":2.0}
						]
					]
				}
			}
		}`,
	)

	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{"metric1"},
		true,
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	assert.ElementsMatch(t, results[0], iterator.KeyValueList{
		{Key: "_step", Value: int64(0)},
		{Key: "metric1", Value: 1.0},
	})
	assert.ElementsMatch(t, results[1], iterator.KeyValueList{
		{Key: "_step", Value: int64(1)},
		{Key: "metric1", Value: 2.0},
	})
}

func TestHistoryReader_GetHistorySteps_MixedParquetAndLiveData(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()

	os.Setenv("WANDB_CACHE_DIR", tempDir)
	defer os.Unsetenv("WANDB_CACHE_DIR")

	// Create parquet file with only step 0
	schema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "metric1", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
	}
	parquetFilePath := filepath.Join(tempDir, "test.parquet")
	iteratortest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
	parquetContent, err := os.ReadFile(parquetFilePath)
	require.NoError(t, err)
	server := createHttpServer(t, respondWithParquetContent(t, parquetContent))

	mockGQL := gqlmock.NewMockClient()

	// Mock RunParquetHistory with parquet files AND live data starting
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		fmt.Sprintf(`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": ["%s/test.parquet"],
						"liveData": [
							{"_step": 1}
						]
					}
				}
			}
		}`, server.URL),
	)

	// Mock HistoryPage for the live data request
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("HistoryPage"),
		`{
			"project": {
				"run": {
					"history": [
						"{\"_step\":1,\"metric1\":2.0}"
					]
				}
			}
		}`,
	)

	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{},
		true,
	)
	require.NoError(t, err)

	// Request data that spans both parquet (step 0) and live data (step 1)
	results, err := reader.GetHistorySteps(ctx, 0, 2)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	assert.ElementsMatch(t, results[0], iterator.KeyValueList{
		{Key: "_step", Value: int64(0)},
		{Key: "metric1", Value: 1.0},
	})
	assert.ElementsMatch(t, results[1], iterator.KeyValueList{
		{Key: "_step", Value: int64(1)},
		{Key: "metric1", Value: 2.0},
	})
}

func TestHistoryReader_GetHistorySteps_NoPanicOnInvalidLiveData(t *testing.T) {
	ctx := t.Context()
	mockGQL := gqlmock.NewMockClient()

	// Mock RunParquetHistory with no parquet files, only live data
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": [],
						"liveData": ["invalid"]
					}
				}
			}
		}`,
	)

	_, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{},
		false,
	)
	assert.ErrorContains(t, err, "expected LiveData to be map[string]any")
}

func TestHistoryReader_GetHistorySteps_NoPanicOnMissingStepKey(t *testing.T) {
	ctx := t.Context()
	mockGQL := gqlmock.NewMockClient()

	// Mock RunParquetHistory with no parquet files, only live data
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": [],
						"liveData": [{"metric1": 1.0}]
					}
				}
			}
		}`,
	)

	_, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{},
		false,
	)
	assert.ErrorContains(t, err, "expected LiveData to contain step key")
}

func TestHistoryReader_GetHistorySteps_NoPanicOnNonConvertibleStepValue(t *testing.T) {
	ctx := t.Context()
	mockGQL := gqlmock.NewMockClient()

	// Mock RunParquetHistory with no parquet files, only live data
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": [],
						"liveData": [{"_step": "invalid"}]
					}
				}
			}
		}`,
	)

	_, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{},
		false,
	)
	assert.ErrorContains(t, err, "expected step to be float64")
}

func TestHistoryReader_GetHistorySteps_ConvertsStepValueToInt(t *testing.T) {
	tests := []struct {
		name          string
		stepValue     string
		expectError   bool
		errorContains string
	}{
		{
			name:        "int value should work",
			stepValue:   "1",
			expectError: false,
		},
		{
			name:        "float64 value should work",
			stepValue:   "1.0",
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctx := t.Context()
			mockGQL := gqlmock.NewMockClient()

			// Mock RunParquetHistory with no parquet files, only live data
			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("RunParquetHistory"),
				fmt.Sprintf(`{
					"project": {
						"run": {
							"parquetHistory": {
								"parquetUrls": [],
								"liveData": [{"_step": %s}]
							}
						}
					}
				}`, tt.stepValue),
			)

			_, err := New(
				ctx,
				"test-entity",
				"test-project",
				"test-run-id",
				mockGQL,
				retryablehttp.NewClient(),
				[]string{},
				false,
			)
			assert.NoError(t, err)
		})
	}
}
