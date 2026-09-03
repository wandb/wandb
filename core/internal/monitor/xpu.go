package monitor

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var errXPUClosed = errors.New("monitor: xpu resource is closed")

// XPU monitors GPUs (Nvidia, AMD, Apple) and Google TPUs via the
// wandb-xpu sidecar binary.
//
// The sidecar is started by the first Sample or Probe call, not by NewXPU.
type XPU struct {
	ctx             context.Context
	resourceManager *XPUResourceManager

	pid          int32
	gpuDeviceIds []int32

	startOnce        sync.Once
	startErrReported atomic.Bool

	mu          sync.Mutex
	closed      bool
	client      spb.SystemMonitorServiceClient
	resourceRef XPUResourceManagerRef
	startErr    error
}

// NewXPU returns an XPU resource whose sidecar start and requests are
// canceled together with ctx.
func NewXPU(
	ctx context.Context,
	resourceManager *XPUResourceManager,
	pid int32,
	gpuDeviceIds []int32,
) *XPU {
	return &XPU{
		ctx:             ctx,
		resourceManager: resourceManager,
		pid:             pid,
		gpuDeviceIds:    gpuDeviceIds,
	}
}

// Sample collects hardware metrics.
//
// A sidecar start failure is returned once; later samples return nothing.
func (a *XPU) Sample() (*spb.StatsRecord, error) {
	ctx, cancel := context.WithTimeout(a.ctx, defaultSamplingInterval)
	defer cancel()

	client, err := a.getClient(ctx)
	if err != nil {
		if errors.Is(err, errXPUClosed) || a.startErrReported.Swap(true) {
			return nil, nil
		}
		return nil, err
	}

	stats, err := client.GetStats(
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
	client, err := a.getClient(ctx)
	if err != nil {
		return nil
	}

	e, err := client.GetMetadata(ctx, &spb.GetMetadataRequest{})
	if err != nil {
		return nil
	}
	return e.GetRecord().GetEnvironment()
}

// Close releases the sidecar reference if one was acquired.
//
// Close does not wait for a start that is still in progress; getClient
// hands the reference back when that start completes.
func (a *XPU) Close() {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.closed {
		return
	}
	a.closed = true

	if a.client != nil {
		a.resourceManager.Release(a.resourceRef)
	}
}

// getClient returns the sidecar client, starting the sidecar on first use.
//
// The outcome of the first start, success or failure, is kept for the
// lifetime of the resource.
func (a *XPU) getClient(ctx context.Context) (spb.SystemMonitorServiceClient, error) {
	a.startOnce.Do(func() {
		client, ref, err := a.resourceManager.Acquire(ctx)

		a.mu.Lock()
		defer a.mu.Unlock()

		if a.closed {
			if err == nil {
				a.resourceManager.Release(ref)
			}
			return
		}
		a.client, a.resourceRef, a.startErr = client, ref, err
	})

	a.mu.Lock()
	defer a.mu.Unlock()

	if a.closed {
		return nil, errXPUClosed
	}
	return a.client, a.startErr
}
