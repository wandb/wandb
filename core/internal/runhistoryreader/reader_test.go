// These tests mock Rust FFI calls by creating Go-allocated memory and converting
// pointers to uintptr. The race detector's checkptr instrumentation correctly
// identifies this as potentially unsafe (Go's GC can move memory, invalidating
// the uintptr). Since the real production code uses actual Rust-allocated memory
// (which doesn't move), this is only a limitation of the test mock, not the
// production code. These tests are excluded when building with -race.

//go:build !race

package runhistoryreader

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"unsafe"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
)

// mockKVDataStore keeps binary-encoded data alive so FFI pointers remain valid.
type mockKVDataStore struct {
	data [][]byte
}

func newMockKVDataStore() *mockKVDataStore {
	return &mockKVDataStore{data: make([][]byte, 0)}
}

func (m *mockKVDataStore) store(data []byte) (uintptr, uintptr) {
	dataCopy := make([]byte, len(data))
	copy(dataCopy, data)
	m.data = append(m.data, dataCopy)

	if len(dataCopy) == 0 {
		// Return null pointer for empty data
		return 0, 0
	}

	storedSlice := m.data[len(m.data)-1]
	ptr := uintptr(unsafe.Pointer(&storedSlice[0]))
	return ptr, ptr
}

// columnDef describes a column for the test binary encoder.
type columnDef struct {
	name    string
	colType string // "int64" or "float64"
}

// createMockRustArrowWrapper creates a mock wrapper that returns data
// in a binary KV format.
func createMockRustArrowWrapper(
	t *testing.T,
	columns []columnDef,
	datasetMap map[uintptr][]map[string]any,
) *ffi.RustArrowWrapper {
	if t != nil {
		t.Helper()
	}

	if columns == nil {
		columns = []columnDef{{name: "_step", colType: "int64"}}
	}

	dataStore := newMockKVDataStore()
	nextReaderID := uintptr(1000)
	readerToDataset := make(map[uintptr][]map[string]any)
	// Store allocated pointers so they don't get garbage collected
	allocatedPointers := make([]*uintptr, 0)
	assignedDatasets := make(map[uintptr]bool)

	var emptyVecPtr, emptyDataPtr uintptr
	var emptyLen uint64
	if len(datasetMap) == 0 {
		emptyBuf := createKVBinaryStream(columns, []map[string]any{})
		emptyVecPtr, emptyDataPtr = dataStore.store(emptyBuf)
		emptyLen = uint64(len(emptyBuf))
	}

	return ffi.RustArrowWrapperTester(
		func(
			filePath *byte,
			columnNames **byte,
			numColumns int,
			outError **byte,
		) unsafe.Pointer {
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
		func(
			readerPtr unsafe.Pointer,
			minStep int64,
			maxStep int64,
			outResult *ffi.StepScanResult,
		) *byte {
			if len(readerToDataset) == 0 {
				outResult.VecPtr = emptyVecPtr
				outResult.DataPtr = emptyDataPtr
				outResult.DataLen = emptyLen
				outResult.NumRowsReturned = 0
				return nil
			}

			readerID := *(*uintptr)(readerPtr)
			dataset, ok := readerToDataset[readerID]
			if !ok {
				emptyBuf := createKVBinaryStream(columns, []map[string]any{})
				vecPtr, dataPtr := dataStore.store(emptyBuf)
				outResult.VecPtr = vecPtr
				outResult.DataPtr = dataPtr
				outResult.DataLen = uint64(len(emptyBuf))
				outResult.NumRowsReturned = 0
				return nil
			}

			// Filter data based on step range (exclusive of maxStep)
			filteredData := []map[string]any{}
			for _, row := range dataset {
				step := row["_step"].(int64)
				if step >= minStep && step < maxStep {
					filteredData = append(filteredData, row)
				}
			}

			kvBytes := createKVBinaryStream(columns, filteredData)
			vecPtr, dataPtr := dataStore.store(kvBytes)

			outResult.VecPtr = vecPtr
			outResult.DataPtr = dataPtr
			outResult.DataLen = uint64(len(kvBytes))
			outResult.NumRowsReturned = uint64(len(filteredData))

			return nil
		},
	)
}

// createKVBinaryStream builds a KV binary stream for testing.
func createKVBinaryStream(
	columns []columnDef,
	data []map[string]any,
) []byte {
	buf := make([]byte, 0, 256)

	// num_columns
	buf = binary.LittleEndian.AppendUint32(buf, uint32(len(columns)))

	// column names
	for _, col := range columns {
		nameBytes := []byte(col.name)
		buf = binary.LittleEndian.AppendUint32(buf, uint32(len(nameBytes)))
		buf = append(buf, nameBytes...)
	}

	// num_rows
	buf = binary.LittleEndian.AppendUint32(buf, uint32(len(data)))

	// row data
	for _, row := range data {
		for _, col := range columns {
			value, exists := row[col.name]
			if !exists || value == nil {
				buf = append(buf, 0 /* Null type */)
				continue
			}

			switch col.colType {
			case "int64":
				buf = append(buf, 1 /* Int64 type */)
				var v int64
				switch tv := value.(type) {
				case int64:
					v = tv
				case float64:
					v = int64(tv)
				case int:
					v = int64(tv)
				}
				buf = binary.LittleEndian.AppendUint64(buf, uint64(v))

			case "float64":
				buf = append(buf, 3 /* Float64 type */)
				var v float64
				switch tv := value.(type) {
				case float64:
					v = tv
				case int64:
					v = float64(tv)
				case int:
					v = float64(tv)
				}
				buf = binary.LittleEndian.AppendUint64(buf, math.Float64bits(v))

			case "string":
				buf = append(buf, 4 /* String type */)
				s := value.(string)
				buf = binary.LittleEndian.AppendUint32(buf, uint32(len(s)))
				buf = append(buf, []byte(s)...)

			default:
				buf = append(buf, 0 /* Null type */)
			}
		}
	}

	return buf
}

// createDummyFileContent creates minimal content for HTTP server responses.
// The mock FFI wrapper ignores actual file content.
func createDummyFileContent() []byte {
	return []byte("dummy-parquet-content-for-test")
}

func respondWithContent(
	t *testing.T,
	content []byte,
) func(responseWriter http.ResponseWriter, request *http.Request) {
	t.Helper()

	return func(responseWriter http.ResponseWriter, request *http.Request) {
		responseWriter.Header().Set("Accept-Ranges", "bytes")

		// Handle range requests for remote reading
		rangeHeader := request.Header.Get("Range")
		if rangeHeader == "" {
			_, err := responseWriter.Write(content)
			require.NoError(t, err)
			return
		}

		var start, end int64
		_, err := fmt.Sscanf(rangeHeader, "bytes=%d-%d", &start, &end)
		require.NoError(t, err)
		responseWriter.Header().Set(
			"Content-Range",
			fmt.Sprintf("bytes %d-%d/%d", start, end, len(content)),
		)
		responseWriter.WriteHeader(http.StatusPartialContent)

		minLength := min(end+1, int64(len(content)))
		_, err = responseWriter.Write(content[start:minLength])
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

func TestHistoryReader_CreatesCacheDirIfNotExists(t *testing.T) {
	ctx := t.Context()
	nonExistentDir := filepath.Join(t.TempDir(), "deeply", "nested", "cache")
	t.Setenv("WANDB_CACHE_DIR", nonExistentDir)

	dummyContent := createDummyFileContent()
	server := createHttpServer(t, respondWithContent(t, dummyContent))
	mockGQL := mockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)
	rustArrowWrapper := createMockRustArrowWrapper(
		t,
		[]columnDef{{name: "_step", colType: "int64"}},
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

	columns := []columnDef{
		{name: "_step", colType: "int64"},
		{name: "metric1", colType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
		{"_step": int64(1), "metric1": 2.0},
		{"_step": int64(2), "metric1": 3.0},
	}

	dummyContent := createDummyFileContent()
	server := createHttpServer(t, respondWithContent(t, dummyContent))
	mockGQL := mockGraphQLWithParquetUrls(
		[]string{server.URL + "/test.parquet"},
	)
	rustArrowWrapper := createMockRustArrowWrapper(
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

	// Ensure we use a clean cache directory for this test
	os.Setenv("WANDB_CACHE_DIR", tempDir)
	defer os.Unsetenv("WANDB_CACHE_DIR")

	columns := []columnDef{
		{name: "_step", colType: "int64"},
		{name: "metric1", colType: "float64"},
	}
	data1 := []map[string]any{
		{"_step": int64(0), "metric1": 0.0},
		{"_step": int64(1), "metric1": 1.0},
	}
	data2 := []map[string]any{
		{"_step": int64(3), "metric1": 3.0},
		{"_step": int64(4), "metric1": 4.0},
	}

	dummyContent := createDummyFileContent()
	servers := make([]*httptest.Server, 2)
	for i := range 2 {
		servers[i] = createHttpServer(
			t,
			respondWithContent(t, dummyContent),
		)
	}
	mockGQL := mockGraphQLWithParquetUrls([]string{
		servers[0].URL + "/test1.parquet",
		servers[1].URL + "/test2.parquet",
	})
	rustWrapper := createMockRustArrowWrapper(t, columns, map[uintptr][]map[string]any{
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

	columns := []columnDef{
		{name: "_step", colType: "int64"},
		{name: "metric1", colType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
		{"_step": int64(1), "metric1": 2.0},
		{"_step": int64(2), "metric1": 3.0},
	}

	dummyContent := createDummyFileContent()
	server := createHttpServer(t, respondWithContent(t, dummyContent))
	mockGQL := mockGraphQLWithParquetUrls([]string{
		server.URL + "/test.parquet",
	})
	rustWrapper := createMockRustArrowWrapper(
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

	columns := []columnDef{
		{name: "_step", colType: "int64"},
		{name: "metric1", colType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "metric1": 1.0},
	}

	dummyContent := createDummyFileContent()
	server := createHttpServer(t, respondWithContent(t, dummyContent))

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

	columns := []columnDef{
		{name: "_step", colType: "int64"},
		{name: "metric1", colType: "float64"},
	}
	// Parquet contains steps 5 and 10 (higher than live data).
	parquetData := []map[string]any{
		{"_step": int64(5), "metric1": 50.0},
		{"_step": int64(10), "metric1": 100.0},
	}

	dummyContent := createDummyFileContent()
	server := createHttpServer(t, respondWithContent(t, dummyContent))

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

	rustWrapper := createMockRustArrowWrapper(
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
