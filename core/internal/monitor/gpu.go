package monitor

import (
	"context"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// GPU is used to monitor Nvidia, AMD, and Apple ARM GPUs.
//
// It collects GPU metrics from the gpu_stats binary via gRPC.
type GPU struct {
	resourceManager *GPUResourceManager
	resourceRef     GPUResourceManagerRef

	// pid of the process to collect process-specific metrics for.
	pid int32

	// gpuDeviceIds is a list of GPU IDs to collect metrics for.
	//
	// If empty, all GPUs are monitored.
	gpuDeviceIds []int32

	// client is the gRPC client for the SystemMonitorService.
	client spb.SystemMonitorServiceClient
}

func NewGPU(
	resourceManager *GPUResourceManager,
	pid int32,
	gpuDeviceIds []int32,
) (*GPU, error) {
	g := &GPU{
		resourceManager: resourceManager,
		gpuDeviceIds:    gpuDeviceIds,
	}

	client, ref, err := resourceManager.Acquire()
	if err != nil {
		return nil, err
	}

	g.resourceRef = ref
	g.client = client

	return g, nil
}

// Sample returns GPU metrics such as power usage, temperature, and utilization.
//
// The metrics are collected from the gpu_stats binary via gRPC.
func (g *GPU) Sample() (*spb.StatsRecord, error) {
	stats, err := g.client.GetStats(
		context.Background(),
		&spb.GetStatsRequest{Pid: g.pid, GpuDeviceIds: g.gpuDeviceIds},
	)
	if err != nil {
		return nil, err
	}

	metrics := stats.GetRecord().GetStats()
	if len(metrics.Item) == 0 {
		return nil, nil
	}

	return metrics, nil
}

// Probe returns static information about the GPU.
func (g *GPU) Probe(ctx context.Context) *spb.EnvironmentRecord {
	e, err := g.client.GetMetadata(ctx, &spb.GetMetadataRequest{})
	if err != nil {
		return nil
	}
	return e.GetRecord().GetEnvironment()
}

// Close shuts down the gpu_stats binary and releases resources.
func (g *GPU) Close() {
	g.resourceManager.Release(g.resourceRef)
}
