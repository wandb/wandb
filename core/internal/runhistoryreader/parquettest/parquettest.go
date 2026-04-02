// Package parquettest provides shared test utilities for mocking the
// Rust FFI parquet reader and related HTTP/GraphQL infrastructure.
//
// These helpers create Go-allocated memory and convert pointers to uintptr
// to simulate Rust FFI responses. The race detector's checkptr
// instrumentation flags this as unsafe, so tests using these helpers
// must use the //go:build !race constraint.

//go:build !race

package parquettest

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"testing"
	"unsafe"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
)

// ColumnDef describes a column for the test binary encoder.
type ColumnDef struct {
	Name    string
	ColType string // "int64", "float64", or "string"
}

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
		return 0, 0
	}

	storedSlice := m.data[len(m.data)-1]
	ptr := uintptr(unsafe.Pointer(&storedSlice[0]))
	return ptr, ptr
}

// CreateKVBinaryStream builds a KV binary stream matching the Rust FFI
// serialization format, for testing.
func CreateKVBinaryStream(
	columns []ColumnDef,
	data []map[string]any,
) []byte {
	buf := make([]byte, 0, 256)

	buf = binary.LittleEndian.AppendUint32(buf, uint32(len(columns)))

	for _, col := range columns {
		nameBytes := []byte(col.Name)
		buf = binary.LittleEndian.AppendUint32(buf, uint32(len(nameBytes)))
		buf = append(buf, nameBytes...)
	}

	buf = binary.LittleEndian.AppendUint32(buf, uint32(len(data)))

	for _, row := range data {
		for _, col := range columns {
			value, exists := row[col.Name]
			if !exists || value == nil {
				buf = append(buf, 0 /* Null type */)
				continue
			}

			switch col.ColType {
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

// CreateMockRustArrowWrapper creates a mock RustArrowWrapper that returns
// data in the binary KV format. The datasetMap maps arbitrary keys to
// datasets; each dataset is assigned to a reader in creation order,
// supporting multi-file scenarios.
//
// Pass nil columns to default to a single "_step" int64 column.
// Pass nil/empty datasetMap for an empty reader.
func CreateMockRustArrowWrapper(
	t *testing.T,
	columns []ColumnDef,
	datasetMap map[uintptr][]map[string]any,
) *ffi.RustArrowWrapper {
	if t != nil {
		t.Helper()
	}

	if columns == nil {
		columns = []ColumnDef{{Name: "_step", ColType: "int64"}}
	}

	dataStore := newMockKVDataStore()
	nextReaderID := uintptr(1000)
	readerToDataset := make(map[uintptr][]map[string]any)
	allocatedPointers := make([]*uintptr, 0)
	assignedDatasets := make(map[uintptr]bool)

	var emptyVecPtr, emptyDataPtr uintptr
	var emptyLen uint64
	if len(datasetMap) == 0 {
		emptyBuf := CreateKVBinaryStream(columns, []map[string]any{})
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

			readerID := nextReaderID
			nextReaderID += 100

			for datasetID, dataset := range datasetMap {
				if !assignedDatasets[datasetID] {
					readerToDataset[readerID] = dataset
					assignedDatasets[datasetID] = true
					break
				}
			}

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
				emptyBuf := CreateKVBinaryStream(columns, []map[string]any{})
				vecPtr, dataPtr := dataStore.store(emptyBuf)
				outResult.VecPtr = vecPtr
				outResult.DataPtr = dataPtr
				outResult.DataLen = uint64(len(emptyBuf))
				outResult.NumRowsReturned = 0
				return nil
			}

			filteredData := []map[string]any{}
			for _, row := range dataset {
				step := row["_step"].(int64)
				if step >= minStep && step < maxStep {
					filteredData = append(filteredData, row)
				}
			}

			kvBytes := CreateKVBinaryStream(columns, filteredData)
			vecPtr, dataPtr := dataStore.store(kvBytes)

			outResult.VecPtr = vecPtr
			outResult.DataPtr = dataPtr
			outResult.DataLen = uint64(len(kvBytes))
			outResult.NumRowsReturned = uint64(len(filteredData))

			return nil
		},
	)
}

// DummyFileContent creates minimal content for HTTP server responses.
// The mock FFI wrapper ignores actual file content.
func DummyFileContent() []byte {
	return []byte("dummy-parquet-content-for-test")
}

// RespondWithContent returns an http.HandlerFunc that serves the given
// content, supporting HTTP range requests.
func RespondWithContent(
	t *testing.T,
	content []byte,
) func(http.ResponseWriter, *http.Request) {
	t.Helper()

	return func(responseWriter http.ResponseWriter, request *http.Request) {
		responseWriter.Header().Set("Accept-Ranges", "bytes")

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

// CreateHTTPServer creates an httptest.Server with the given handler,
// registering cleanup via t.Cleanup.
func CreateHTTPServer(
	t *testing.T,
	handler func(http.ResponseWriter, *http.Request),
) *httptest.Server {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(handler))
	t.Cleanup(server.Close)

	return server
}

// MockGraphQLWithParquetUrls creates a gqlmock.MockClient stubbed to
// return the given parquet URLs for a RunParquetHistory query.
func MockGraphQLWithParquetUrls(urls []string) *gqlmock.MockClient {
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
