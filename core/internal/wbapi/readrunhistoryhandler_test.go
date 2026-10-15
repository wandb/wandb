package wbapi

import (
	"testing"
	"unsafe"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestRunHistoryAPIHandler_ScanNextStepSurvivesWireRoundTrip(t *testing.T) {
	client := gqlmock.NewMockClient()
	client.StubMatchOnce(gqlmock.WithOpName("RunParquetHistory"),
		`{"project":{"run":{"parquetHistory":{"parquetUrls":["https://example.com/history.parquet"],"liveData":[]}}}}`)
	wrapper := ffi.RustArrowWrapperTester(
		func(*byte, **byte, int, **byte) unsafe.Pointer {
			return unsafe.Pointer(new(byte))
		},
		func(_ unsafe.Pointer, _, _ int64, result *ffi.StepScanResult) *byte {
			*result = ffi.StepScanResult{}
			return nil
		},
		func(unsafe.Pointer) int64 { return 5_000_000 },
	)
	reader, err := runhistoryreader.New(t.Context(), "entity", "project", "run-id", client, nil, []string{"_step"}, false, wrapper)
	require.NoError(t, err)
	defer reader.Release()
	handler := NewRunHistoryAPIHandler(client, nil, observability.NewNoOpLogger())
	handler.scanHistoryReaders[1] = reader

	response := handler.HandleRequest(t.Context(), &spb.ReadRunHistoryRequest{
		Request: &spb.ReadRunHistoryRequest_ScanRunHistory{
			ScanRunHistory: &spb.ScanRunHistory{RequestId: 1, MinStep: 0, MaxStep: 1000},
		},
	})
	wire, err := proto.Marshal(response)
	require.NoError(t, err)
	var decoded spb.ApiResponse
	require.NoError(t, proto.Unmarshal(wire, &decoded))
	page := decoded.GetReadRunHistoryResponse().GetRunHistory()
	require.NotNil(t, page)
	require.Empty(t, page.HistoryRows)
	require.NotNil(t, page.NextStep)
	require.Equal(t, int64(5_000_000), page.GetNextStep())
}
