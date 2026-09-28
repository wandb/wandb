package systemmetrics_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSamples(t *testing.T) {
	rec := &spb.SystemMetricsRecord{
		Host: &spb.HostMetrics{
			DiskIo: []*spb.DiskIoMetrics{{Device: "nvme0n1", ReadBytes: proto.Uint64(5 << 20)}},
		},
		Accelerators: []*spb.AcceleratorMetrics{{
			Type:         spb.AcceleratorType_NVIDIA_GPU,
			Index:        1,
			Host:         "node1",
			TemperatureC: proto.Float64(65),
			Ext: &spb.AcceleratorMetrics_Nvidia{Nvidia: &spb.NvidiaMetrics{
				SmClockMhz: proto.Float64(1980),
			}},
		}},
		TpuRuntime: &spb.TpuRuntimeMetrics{
			Distributions: []*spb.TpuRuntimeMetrics_Distribution{
				{
					Kind:  spb.TpuRuntimeMetrics_HLO_EXEC_TIMING,
					Label: "program_main",
					P50:   proto.Float64(90),
				},
			},
		},
		Generic: []*spb.GenericMetric{{
			Source: "dcgm",
			Name:   "DCGM_FI_DEV_XID_ERRORS",
			Labels: []*spb.MetricLabel{{Key: "gpu", Value: "0"}, {Key: "Hostname", Value: "h1"}},
			Kind:   spb.MetricInfo_COUNTER,
			Unit:   "1",
			Value:  proto.Float64(3),
		}},
	}

	byPath := map[string]systemmetrics.Sample{}
	for _, s := range systemmetrics.Samples(rec) {
		byPath[s.Path] = s
	}
	require.Len(t, byPath, 5)

	disk := byPath["host.disk_io.read_bytes"]
	assert.Equal(t, "Disk Read", disk.Info.GetDisplay())
	assert.Equal(t, "By", disk.Info.GetUnit())
	assert.Equal(t, spb.MetricInfo_COUNTER, disk.Info.GetKind())
	assert.Equal(t, "nvme0n1", disk.Vars["device"])
	assert.Equal(t, float64(5<<20), disk.Value)
	assert.Equal(t, spb.AcceleratorType_ACCELERATOR_UNSPECIFIED, disk.Accelerator)

	temp := byPath["accelerators.temperature_c"]
	assert.Equal(t, spb.AcceleratorType_NVIDIA_GPU, temp.Accelerator)
	assert.Equal(t, "1", temp.Vars["index"])
	assert.Equal(t, "node1", temp.Vars["host"])
	assert.Equal(t, "Cel", temp.Info.GetUnit())

	clock := byPath["accelerators.nvidia.sm_clock_mhz"]
	assert.Equal(t, spb.AcceleratorType_NVIDIA_GPU, clock.Accelerator)
	assert.Equal(t, "SM Clock", clock.Info.GetDisplay())

	dist := byPath["tpu_runtime.distributions"]
	assert.Equal(t, spb.AcceleratorType_GOOGLE_TPU, dist.Accelerator)
	assert.Equal(t, "HLO Execution Timing", dist.Info.GetDisplay())
	assert.Equal(t, "us", dist.Info.GetUnit())
	assert.Equal(t, map[string]string{"label": "program_main", "stat": "p50"}, dist.Vars)
	assert.Equal(t, 90.0, dist.Value)

	generic := byPath["generic.value"]
	assert.Equal(t, "DCGM_FI_DEV_XID_ERRORS", generic.Info.GetDisplay())
	assert.Equal(t, "1", generic.Info.GetUnit())
	assert.Equal(t, spb.MetricInfo_COUNTER, generic.Info.GetKind())
	assert.Equal(t, "dcgm", generic.Vars["source"])
	assert.Equal(t, "Hostname=h1 gpu=0", generic.Vars["labels"])
	assert.Equal(t, 3.0, generic.Value)
}
