//go:build !race

package leet_test

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"unsafe"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
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

func serveParquetFile(t *testing.T, content []byte) *httptest.Server {
	t.Helper()

	handler := func(responseWriter http.ResponseWriter, request *http.Request) {
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

	server := httptest.NewServer(http.HandlerFunc(handler))
	t.Cleanup(server.Close)

	return server
}

// mockKVDataStore keeps binary-encoded data alive so FFI pointers remain valid.
type mockKVDataStore struct {
	data [][]byte
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

type columnDef struct {
	name    string
	colType string // "int64" or "float64"
}

func createKVBinaryStream(columns []columnDef, data []map[string]any) []byte {
	buf := make([]byte, 0, 256)
	buf = binary.LittleEndian.AppendUint32(buf, uint32(len(columns)))
	for _, col := range columns {
		nameBytes := []byte(col.name)
		buf = binary.LittleEndian.AppendUint32(buf, uint32(len(nameBytes)))
		buf = append(buf, nameBytes...)
	}
	buf = binary.LittleEndian.AppendUint32(buf, uint32(len(data)))

	for _, row := range data {
		for _, col := range columns {
			value, exists := row[col.name]
			if !exists || value == nil {
				buf = append(buf, 0)
				continue
			}
			switch col.colType {
			case "int64":
				buf = append(buf, 1)
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
				buf = append(buf, 3)
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
			default:
				buf = append(buf, 0)
			}
		}
	}
	return buf
}

func createMockRustArrowWrapper(
	t *testing.T,
	columns []columnDef,
	rows []map[string]any,
) *ffi.RustArrowWrapper {
	t.Helper()

	dataStore := &mockKVDataStore{data: make([][]byte, 0)}
	allocatedPointers := make([]*uintptr, 0)

	return ffi.RustArrowWrapperTester(
		func(
			filePath *byte,
			columnNames **byte,
			numColumns int,
			outError **byte,
		) unsafe.Pointer {
			id := new(uintptr)
			*id = 1
			allocatedPointers = append(allocatedPointers, id)
			return unsafe.Pointer(id)
		},
		func(
			readerPtr unsafe.Pointer,
			minStep int64,
			maxStep int64,
			outResult *ffi.StepScanResult,
		) *byte {
			filtered := []map[string]any{}
			for _, row := range rows {
				step := row["_step"].(int64)
				if step >= minStep && step < maxStep {
					filtered = append(filtered, row)
				}
			}

			kvBytes := createKVBinaryStream(columns, filtered)
			vecPtr, dataPtr := dataStore.store(kvBytes)

			outResult.VecPtr = vecPtr
			outResult.DataPtr = dataPtr
			outResult.DataLen = uint64(len(kvBytes))
			outResult.NumRowsReturned = uint64(len(filtered))
			return nil
		},
	)
}

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

	columns := []columnDef{
		{name: "_step", colType: "int64"},
		{name: "loss", colType: "float64"},
	}
	data := []map[string]any{
		{"_step": int64(0), "loss": 1.0},
		{"_step": int64(1), "loss": 0.8},
		{"_step": int64(2), "loss": 0.6},
	}

	dummyContent := []byte("dummy-parquet-content")
	server := serveParquetFile(t, dummyContent)
	mockGQL := mockGraphQLWithParquetUrls([]string{server.URL + "/test.parquet"})
	mockWrapper := createMockRustArrowWrapper(t, columns, data)

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
		context.Background(),
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		retryablehttp.NewClient(),
		runInfo,
		logger,
		mockWrapper,
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
