package monitor

import (
	"context"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// XPU monitors GPUs (Nvidia, AMD, Apple) and Google TPUs via the
// wandb-xpu sidecar binary.
type XPU struct {
	resourceManager *XPUResourceManager
	resourceRef     XPUResourceManagerRef

	pid          int32
	gpuDeviceIds []int32
	client       spb.SystemMonitorServiceClient
}

func NewXPU(
	resourceManager *XPUResourceManager,
	pid int32,
	gpuDeviceIds []int32,
) (*XPU, error) {
	client, ref, err := resourceManager.Acquire()
	if err != nil {
		return nil, err
	}
	return &XPU{
		resourceManager: resourceManager,
		resourceRef:     ref,
		pid:             pid,
		gpuDeviceIds:    gpuDeviceIds,
		client:          client,
	}, nil
}

func (a *XPU) Sample() (*spb.StatsRecord, error) {
	stats, err := a.client.GetStats(
		context.Background(),
		&spb.GetStatsRequest{Pid: a.pid, GpuDeviceIds: a.gpuDeviceIds},
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

func (a *XPU) Probe(ctx context.Context) *spb.EnvironmentRecord {
	e, err := a.client.GetMetadata(ctx, &spb.GetMetadataRequest{})
	if err != nil {
		return nil
	}
	return e.GetRecord().GetEnvironment()
}

func (a *XPU) Close() {
	a.resourceManager.Release(a.resourceRef)
}
