//go:build !race

package leet_test

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"unsafe"

	"github.com/hashicorp/go-retryablehttp"
)
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
