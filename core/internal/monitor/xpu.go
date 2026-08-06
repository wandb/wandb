package monitor

import (
	"context"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// xpuSampleTimeout bounds a single stats request to the wandb-xpu sidecar,
// which can stop responding while blocked in a device query.
const xpuSampleTimeout = 30 * time.Second

// XPU monitors GPUs (Nvidia, AMD, Apple) and Google TPUs via the
// wandb-xpu sidecar binary.
type XPU struct {
	resourceManager *XPUResourceManager
	resourceRef     XPUResourceManagerRef

	pid          int32
	gpuDeviceIds []int32
	client       spb.SystemMonitorServiceClient

	// sampleTimeout is how long to wait for one Sample to complete.
	sampleTimeout time.Duration
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
		sampleTimeout:   xpuSampleTimeout,
	}, nil
}

func (a *XPU) Sample() (*spb.StatsRecord, error) {
	ctx, cancel := context.WithTimeout(context.Background(), a.sampleTimeout)
	defer cancel()

	stats, err := a.client.GetStats(
		ctx,
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
