package monitor

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeSidecar records requests and, like wandb-xpu, reports serials only when asked.
type fakeSidecar struct {
	spb.SystemMonitorServiceClient
	stats    []*spb.GetStatsRequest
	metadata []*spb.GetMetadataRequest
}

func (f *fakeSidecar) GetStats(
	_ context.Context,
	in *spb.GetStatsRequest,
	_ ...grpc.CallOption,
) (*spb.GetStatsResponse, error) {
	f.stats = append(f.stats, in)
	stats := &spb.StatsRecord{Item: []*spb.StatsItem{{Key: "gpu.0.gpu", ValueJson: "1"}}}
	return &spb.GetStatsResponse{
		Record: &spb.Record{RecordType: &spb.Record_Stats{Stats: stats}},
	}, nil
}

func (f *fakeSidecar) GetMetadata(
	_ context.Context,
	in *spb.GetMetadataRequest,
	_ ...grpc.CallOption,
) (*spb.GetMetadataResponse, error) {
	f.metadata = append(f.metadata, in)
	gpu := &spb.GpuNvidiaInfo{Uuid: "GPU-aaa"}
	if in.GetIncludeSerial() {
		gpu.Serial = "1320000000001"
	}
	env := &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{gpu}}
	return &spb.GetMetadataResponse{
		Record: &spb.Record{RecordType: &spb.Record_Environment{Environment: env}},
	}, nil
}

// newFakeXPU returns an XPU whose sidecar is already "running" as fake; never Close it.
func newFakeXPU(provenance bool) (*XPU, *fakeSidecar) {
	fake := &fakeSidecar{}
	rm := NewXPUResourceManager(false)
	rm.collectorConn = &grpc.ClientConn{}
	rm.collectorClient = fake
	return NewXPU(context.Background(), rm, 123, []int32{0, 1}, provenance), fake
}

func TestXPU_WithoutProvenanceRequestsNoSerialOrThrottleReasons(t *testing.T) {
	x, fake := newFakeXPU(false)

	env := x.Probe(context.Background())
	_, err := x.Sample()
	require.NoError(t, err)

	require.Len(t, env.GetGpuNvidia(), 1)
	assert.Empty(t, env.GetGpuNvidia()[0].GetSerial())
	assert.False(t, fake.metadata[0].GetIncludeSerial())
	assert.False(t, fake.stats[0].GetIncludeThrottleReasons())
}

func TestXPU_WithProvenanceRequestsSerialAndThrottleReasons(t *testing.T) {
	x, fake := newFakeXPU(true)

	env := x.Probe(context.Background())
	_, err := x.Sample()
	require.NoError(t, err)

	assert.Equal(t, "1320000000001", env.GetGpuNvidia()[0].GetSerial())
	assert.True(t, fake.metadata[0].GetIncludeSerial())
	assert.True(t, fake.stats[0].GetIncludeThrottleReasons())
	assert.Equal(t, int32(123), fake.stats[0].GetPid())
	assert.Equal(t, []int32{0, 1}, fake.stats[0].GetGpuDeviceIds())
}
