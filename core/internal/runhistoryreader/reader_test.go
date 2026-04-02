// These tests mock Rust FFI calls by creating Go-allocated memory and converting
// pointers to uintptr. The race detector's checkptr instrumentation correctly
// identifies this as potentially unsafe (Go's GC can move memory, invalidating
// the uintptr). Since the real production code uses actual Rust-allocated memory
// (which doesn't move), this is only a limitation of the test mock, not the
// production code. These tests are excluded when building with -race.

//go:build !race

package runhistoryreader

import (
	"fmt"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquettest"
)

func TestHistoryReader_CreatesCacheDirIfNotExists(t *testing.T) {
	ctx := t.Context()
	nonExistentDir := filepath.Join(t.TempDir(), "deeply", "nested", "cache")
	t.Setenv("WANDB_CACHE_DIR", nonExistentDir)

	dummyContent := parquettest.DummyFileContent()
	server := parquettest.CreateHTTPServer(t, parquettest.RespondWithContent(t, dummyContent))
	mockGQL := parquettest.MockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)
	rustArrowWrapper := parquettest.CreateMockRustArrowWrapper(
		t,
		[]parquettest.ColumnDef{{Name: "_step", ColType: "int64"}},
		map[uintptr][]map[string]any{1: {{"_step": int64(0)}}},
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
		rustArrowWrapper,
	)
	require.NoError(t, err)

	info, err := os.Stat(nonExistentDir)
	require.NoError(t, err)
	assert.True(t, info.IsDir())
}

func TestHistoryReader_GetHistorySteps_WithoutKeys(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()
	t.Setenv("WANDB_CACHE_DIR", tempDir)

	columns := []parquettest.ColumnDef{
		{Name: "_step", ColType: "int64"},
		{Name: "metric1", ColType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
		{"_step": int64(1), "metric1": 2.0},
		{"_step": int64(2), "metric1": 3.0},
	}

	dummyContent := parquettest.DummyFileContent()
	server := parquettest.CreateHTTPServer(t, parquettest.RespondWithContent(t, dummyContent))
	mockGQL := parquettest.MockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)
	rustArrowWrapper := parquettest.CreateMockRustArrowWrapper(
		t,
		columns,
		map[uintptr][]map[string]any{1: data},
	)

	serverURL, err := url.Parse(server.URL)
	require.NoError(t, err)

	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		api.NewClient(api.ClientOptions{
			BaseURL:            serverURL,
			CredentialProvider: api.NoopCredentialProvider{},
		}),
		[]string{},
		true,
		rustArrowWrapper,
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 3)
	expectedResults := []parquet.KeyValueList{
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
	t.Setenv("WANDB_CACHE_DIR", tempDir)

	columns := []parquettest.ColumnDef{
		{Name: "_step", ColType: "int64"},
		{Name: "metric1", ColType: "float64"},
	}
	data1 := []map[string]any{
		{"_step": int64(0), "metric1": 0.0},
		{"_step": int64(1), "metric1": 1.0},
	}
	data2 := []map[string]any{
		{"_step": int64(3), "metric1": 3.0},
		{"_step": int64(4), "metric1": 4.0},
	}

	dummyContent := parquettest.DummyFileContent()
	servers := make([]*httptest.Server, 2)
	for i := range 2 {
		servers[i] = parquettest.CreateHTTPServer(
			t,
			parquettest.RespondWithContent(t, dummyContent),
		)
	}
	mockGQL := parquettest.MockGraphQLWithParquetUrls([]string{
		servers[0].URL + "/test1.parquet",
		servers[1].URL + "/test2.parquet",
	})
	rustWrapper := parquettest.CreateMockRustArrowWrapper(t, columns, map[uintptr][]map[string]any{
		1: data1,
		2: data2,
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
		rustWrapper,
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 1, 4)
	assert.NoError(t, err)

	assert.Len(t, results, 2)
	expectedResults := []parquet.KeyValueList{
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

	columns := []parquettest.ColumnDef{
		{Name: "_step", ColType: "int64"},
		{Name: "metric1", ColType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
		{"_step": int64(1), "metric1": 2.0},
		{"_step": int64(2), "metric1": 3.0},
	}

	dummyContent := parquettest.DummyFileContent()
	server := parquettest.CreateHTTPServer(t, parquettest.RespondWithContent(t, dummyContent))
	mockGQL := parquettest.MockGraphQLWithParquetUrls([]string{
		server.URL + "/test.parquet",
	})
	rustWrapper := parquettest.CreateMockRustArrowWrapper(
		t,
		columns,
		map[uintptr][]map[string]any{1: data},
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
		rustWrapper,
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 3)
	expectedResults := []parquet.KeyValueList{
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
		parquettest.CreateMockRustArrowWrapper(nil, nil, nil),
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	assert.ElementsMatch(t, results[0], parquet.KeyValueList{
		{Key: "_step", Value: int64(0)},
		{Key: "metric1", Value: 1.0},
	})
	assert.ElementsMatch(t, results[1], parquet.KeyValueList{
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
		parquettest.CreateMockRustArrowWrapper(nil, nil, nil),
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 10)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	assert.ElementsMatch(t, results[0], parquet.KeyValueList{
		{Key: "_step", Value: int64(0)},
		{Key: "metric1", Value: 1.0},
	})
	assert.ElementsMatch(t, results[1], parquet.KeyValueList{
		{Key: "_step", Value: int64(1)},
		{Key: "metric1", Value: 2.0},
	})
}

func TestHistoryReader_GetHistorySteps_MixedParquetAndLiveData(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()

	os.Setenv("WANDB_CACHE_DIR", tempDir)
	defer os.Unsetenv("WANDB_CACHE_DIR")

	columns := []parquettest.ColumnDef{
		{Name: "_step", ColType: "int64"},
		{Name: "metric1", ColType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
	}

	dummyContent := parquettest.DummyFileContent()
	server := parquettest.CreateHTTPServer(t, parquettest.RespondWithContent(t, dummyContent))

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
	rustWrapper := parquettest.CreateMockRustArrowWrapper(
		t,
		columns,
		map[uintptr][]map[string]any{1: data},
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
		rustWrapper,
	)
	require.NoError(t, err)

	// Request data that spans both parquet (step 0) and live data (step 1)
	results, err := reader.GetHistorySteps(ctx, 0, 2)

	assert.NoError(t, err)
	assert.Len(t, results, 2)
	assert.ElementsMatch(t, results[0], parquet.KeyValueList{
		{Key: "_step", Value: int64(0)},
		{Key: "metric1", Value: 1.0},
	})
	assert.ElementsMatch(t, results[1], parquet.KeyValueList{
		{Key: "_step", Value: int64(1)},
		{Key: "metric1", Value: 2.0},
	})
}

func TestHistoryReader_GetHistorySteps_ResultsSortedByStep(t *testing.T) {
	ctx := t.Context()
	tempDir := t.TempDir()

	os.Setenv("WANDB_CACHE_DIR", tempDir)
	defer os.Unsetenv("WANDB_CACHE_DIR")

	columns := []parquettest.ColumnDef{
		{Name: "_step", ColType: "int64"},
		{Name: "metric1", ColType: "float64"},
	}
	// Parquet contains steps 5 and 10 (higher than live data).
	parquetData := []map[string]any{
		{"_step": int64(5), "metric1": 50.0},
		{"_step": int64(10), "metric1": 100.0},
	}

	dummyContent := parquettest.DummyFileContent()
	server := parquettest.CreateHTTPServer(t, parquettest.RespondWithContent(t, dummyContent))

	mockGQL := gqlmock.NewMockClient()

	// Live data starts at step 0 — lower than parquet data.
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		fmt.Sprintf(`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": ["%s/test.parquet"],
						"liveData": [
							{"_step": 0},
							{"_step": 3},
							{"_step": 7}
						]
					}
				}
			}
		}`, server.URL),
	)

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("HistoryPage"),
		`{
			"project": {
				"run": {
					"history": [
						"{\"_step\":0,\"metric1\":0.0}",
						"{\"_step\":3,\"metric1\":30.0}",
						"{\"_step\":7,\"metric1\":70.0}"
					]
				}
			}
		}`,
	)

	rustWrapper := parquettest.CreateMockRustArrowWrapper(
		t,
		columns,
		map[uintptr][]map[string]any{1: parquetData},
	)

	reader, err := New(
		ctx,
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		[]string{},
		false,
		rustWrapper,
	)
	require.NoError(t, err)

	results, err := reader.GetHistorySteps(ctx, 0, 11)
	require.NoError(t, err)
	require.Len(t, results, 5)

	// Verify results are sorted by _step regardless of source.
	expectedSteps := []int64{0, 3, 5, 7, 10}
	for i, row := range results {
		assert.Equal(t, expectedSteps[i], row.StepValue(),
			"row %d: expected step %d", i, expectedSteps[i])
	}
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
		parquettest.CreateMockRustArrowWrapper(nil, nil, nil),
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
		parquettest.CreateMockRustArrowWrapper(nil, nil, nil),
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
		parquettest.CreateMockRustArrowWrapper(nil, nil, nil),
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
				parquettest.CreateMockRustArrowWrapper(nil, nil, nil),
			)
			assert.NoError(t, err)
		})
	}
}
