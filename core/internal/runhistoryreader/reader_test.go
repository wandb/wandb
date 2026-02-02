// These tests mock Rust FFI calls by creating Go-allocated memory and converting
// pointers to uintptr. The race detector's checkptr instrumentation correctly
// identifies this as potentially unsafe (Go's GC can move memory, invalidating
// the uintptr). Since the real production code uses actual Rust-allocated memory
// (which doesn't move), this is only a limitation of the test mock, not the
// production code. These tests are excluded when building with -race.

//go:build !race

package runhistoryreader

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"unsafe"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/ipc"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
	"github.com/wandb/wandb/core/internal/runhistoryreader/runhistoryreadertest"
)

// mockIPCDataStore keeps IPC data alive during test execution
// It stores the actual byte slices so the pointers remain valid
type mockIPCDataStore struct {
	ipcData [][]byte
}

func newMockIPCDataStore() *mockIPCDataStore {
	return &mockIPCDataStore{
		ipcData: make([][]byte, 0),
	}
}

func (m *mockIPCDataStore) store(data []byte) (uintptr, uintptr) {
	// Make a copy of the data to ensure it's not moved by GC
	dataCopy := make([]byte, len(data))
	copy(dataCopy, data)
	m.ipcData = append(m.ipcData, dataCopy)

	if len(dataCopy) == 0 {
		// Return null pointer for empty data
		return 0, 0
	}

	// Get pointer to the stored data
	// Note: This works without race detector because we keep the slice alive
	// in m.ipcData. With race detector, this file is excluded via build tag.
	storedSlice := m.ipcData[len(m.ipcData)-1]
	ptr := uintptr(unsafe.Pointer(&storedSlice[0]))
	return ptr, ptr
}

// createMockRustArrowWrapper creates a mock wrapper that returns data based on the provided schema and datasets.
// If schema is nil, uses a default empty schema with just _step column.
// If datasets is nil or empty, returns empty results (useful for tests that only use live data).
// datasets is a slice where each element is the data for one file, in the order files are created.
func createMockRustArrowWrapper(
	t *testing.T,
	schema *arrow.Schema,
	datasetMap map[uintptr][]map[string]any,
) *ffi.RustArrowWrapper {
	if t != nil {
		t.Helper()
	}

	// Use default empty schema if none provided
	if schema == nil {
		schema = arrow.NewSchema(
			[]arrow.Field{
				{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			},
			nil,
		)
	}

	dataStore := newMockIPCDataStore()
	nextReaderID := uintptr(1000)
	readerToDataset := make(map[uintptr][]map[string]any)
	// Store allocated pointers so they don't get garbage collected
	allocatedPointers := make([]*uintptr, 0)
	assignedDatasets := make(map[uintptr]bool)

	// If no datasets provided, create empty IPC stream once for efficiency
	var emptyVecPtr, emptyDataPtr uintptr
	var emptyIPCLen uint64
	if len(datasetMap) == 0 {
		emptyIPC := createArrowIPCStream(t, schema, []map[string]any{})
		emptyVecPtr, emptyDataPtr = dataStore.store(emptyIPC)
		emptyIPCLen = uint64(len(emptyIPC))
	}

	return ffi.RustArrowWrapperTester(
		func(filePath *byte, columnNames **byte, numColumns int) unsafe.Pointer {
			// If no datasets, return simple marker
			if len(datasetMap) == 0 {
				id := new(uintptr)
				*id = 1
				allocatedPointers = append(allocatedPointers, id)
				return unsafe.Pointer(id)
			}

			// Assign this reader a unique ID and map it to its dataset
			readerID := nextReaderID
			nextReaderID += 100

			// Map datasets to readers in order of creation
			for datasetID, dataset := range datasetMap {
				if !assignedDatasets[datasetID] {
					readerToDataset[readerID] = dataset
					assignedDatasets[datasetID] = true
					break
				}
			}

			// Allocate memory for the reader ID to return a valid pointer
			id := new(uintptr)
			*id = readerID
			allocatedPointers = append(allocatedPointers, id)
			return unsafe.Pointer(id)
		},
		func(readerPtr unsafe.Pointer, minStep float64, maxStep float64, outResult *ffi.StepScanResult) *byte {
			// If no datasets, return pre-computed empty result
			if len(readerToDataset) == 0 {
				outResult.VecPtr = emptyVecPtr
				outResult.DataPtr = emptyDataPtr
				outResult.DataLen = emptyIPCLen
				outResult.NumRowsReturned = 0
				return nil
			}

			readerID := *(*uintptr)(readerPtr)
			dataset, ok := readerToDataset[readerID]
			if !ok {
				// Return empty if we don't have data for this reader
				emptyIPC := createArrowIPCStream(t, schema, []map[string]any{})
				vecPtr, dataPtr := dataStore.store(emptyIPC)
				outResult.VecPtr = vecPtr
				outResult.DataPtr = dataPtr
				outResult.DataLen = uint64(len(emptyIPC))
				outResult.NumRowsReturned = 0
				return nil
			}

			// Filter data based on step range (exclusive of maxStep)
			filteredData := []map[string]any{}
			for _, row := range dataset {
				step := row["_step"].(int64)
				if float64(step) >= minStep && float64(step) < maxStep {
					filteredData = append(filteredData, row)
				}
			}

			// Generate Arrow IPC stream from filtered data
			ipcBytes := createArrowIPCStream(t, schema, filteredData)
			vecPtr, dataPtr := dataStore.store(ipcBytes)

			outResult.VecPtr = vecPtr
			outResult.DataPtr = dataPtr
			outResult.DataLen = uint64(len(ipcBytes))
			outResult.NumRowsReturned = uint64(len(filteredData))

			return nil
		},
	)
}

// createArrowIPCStream creates an Arrow IPC stream from the given schema and data
// This is used to mock the output from the Rust FFI functions
func createArrowIPCStream(
	t *testing.T,
	schema *arrow.Schema,
	data []map[string]any,
) []byte {
	if t != nil {
		t.Helper()
	}

	// Create builders for each field
	builders := make([]array.Builder, 0, schema.NumFields())
	for _, field := range schema.Fields() {
		var builder array.Builder
		switch field.Type {
		case arrow.PrimitiveTypes.Int64:
			builder = array.NewInt64Builder(memory.DefaultAllocator)
		case arrow.PrimitiveTypes.Float64:
			builder = array.NewFloat64Builder(memory.DefaultAllocator)
		default:
			if t != nil {
				t.Fatalf("unsupported type: %v", field.Type)
			}
			panic(fmt.Sprintf("unsupported type: %v", field.Type))
		}
		builders = append(builders, builder)
	}
	defer func() {
		for _, b := range builders {
			b.Release()
		}
	}()

	// Populate builders with data
	for _, row := range data {
		for i, field := range schema.Fields() {
			value := row[field.Name]
			switch b := builders[i].(type) {
			case *array.Int64Builder:
				b.Append(value.(int64))
			case *array.Float64Builder:
				b.Append(value.(float64))
			}
		}
	}

	// Create arrays from builders
	arrays := make([]arrow.Array, 0, len(builders))
	for _, builder := range builders {
		arrays = append(arrays, builder.NewArray())
	}
	defer func() {
		for _, arr := range arrays {
			arr.Release()
		}
	}()

	// Create record batch
	numRows := int64(len(data))
	record := array.NewRecordBatch(schema, arrays, numRows)
	defer record.Release()

	// Write to IPC stream
	var buf bytes.Buffer
	writer := ipc.NewWriter(
		&buf,
		ipc.WithSchema(schema),
		ipc.WithAllocator(memory.DefaultAllocator),
	)
	defer writer.Close()

	err := writer.Write(record)
	if err != nil {
		if t != nil {
			require.NoError(t, err)
		} else {
			panic(fmt.Sprintf("failed to write IPC: %v", err))
		}
	}

	return buf.Bytes()
}

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
	runhistoryreadertest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
	parquetContent, err := os.ReadFile(parquetFilePath)
	require.NoError(t, err)
	server := createHttpServer(t, respondWithParquetContent(t, parquetContent))
	mockGQL := mockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)
	rustArrowWrapper := createMockRustArrowWrapper(
		t,
		schema,
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

	// Ensure we use a clean cache directory for this test
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
		runhistoryreadertest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)

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
	rustWrapper := createMockRustArrowWrapper(t, schema, map[uintptr][]map[string]any{
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
	fmt.Println("results", results)
	for i, result := range results {
		assert.ElementsMatch(t, expectedResults[i], result, "Result %d doesn't match expected", i)
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
	runhistoryreadertest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
	parquetContent, err := os.ReadFile(parquetFilePath)
	require.NoError(t, err)
	server := createHttpServer(t, respondWithParquetContent(t, parquetContent))
	mockGQL := mockGraphQLWithParquetUrls([]string{
		server.URL + "/test.parquet",
	})
	filteredSchema := arrow.NewSchema(
		[]arrow.Field{
			{Name: "_step", Type: arrow.PrimitiveTypes.Int64},
			{Name: "metric1", Type: arrow.PrimitiveTypes.Float64},
		},
		nil,
	)
	filteredData := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
		{"_step": int64(1), "metric1": 2.0},
		{"_step": int64(2), "metric1": 3.0},
	}
	rustWrapper := createMockRustArrowWrapper(
		t,
		filteredSchema,
		map[uintptr][]map[string]any{1: filteredData},
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
		createMockRustArrowWrapper(nil, nil, nil),
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
		createMockRustArrowWrapper(nil, nil, nil),
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
	runhistoryreadertest.CreateTestParquetFileFromData(t, parquetFilePath, schema, data)
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
	rustWrapper := createMockRustArrowWrapper(
		t,
		schema,
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
		createMockRustArrowWrapper(nil, nil, nil),
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
		createMockRustArrowWrapper(nil, nil, nil),
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
		createMockRustArrowWrapper(nil, nil, nil),
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
				createMockRustArrowWrapper(nil, nil, nil),
			)
			assert.NoError(t, err)
		})
	}
}
