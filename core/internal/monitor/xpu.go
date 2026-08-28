package monitor

import (
	"context"
	"errors"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// XPUManager manages access to the shared wandb-xpu sidecar.
type XPUManager interface {
	Acquire() (spb.SystemMonitorServiceClient, XPUResourceManagerRef, error)
	Release(XPUResourceManagerRef)
}

// XPU monitors GPUs (Nvidia, AMD, Apple) and Google TPUs via the
// wandb-xpu sidecar binary.
type XPU struct {
	mu              sync.Mutex
	resourceManager XPUManager
	resourceRef     XPUResourceManagerRef
	initialized     bool
	closed          bool
	initErr         error
	initErrReported bool

	pid          int32
	gpuDeviceIds []int32
	client       spb.SystemMonitorServiceClient
}

func NewXPU(
	resourceManager XPUManager,
	pid int32,
	gpuDeviceIds []int32,
) (*XPU, error) {
	if resourceManager == nil {
		return nil, errors.New("monitor: xpu resource manager is nil")
	}

	return &XPU{
		resourceManager: resourceManager,
		pid:             pid,
		gpuDeviceIds:    gpuDeviceIds,
	}, nil
}

func (a *XPU) Sample() (*spb.StatsRecord, error) {
	client, err := a.getClient()
	if err != nil {
		a.mu.Lock()
		shouldReport := !a.initErrReported
		a.initErrReported = true
		a.mu.Unlock()
		if shouldReport {
			return nil, err
		}
		return nil, nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), defaultSamplingInterval)
	defer cancel()

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
	client, err := a.getClient()
	if err != nil {
		return nil
	}

	e, err := client.GetMetadata(ctx, &spb.GetMetadataRequest{})
	if err != nil {
		return nil
	}
	return e.GetRecord().GetEnvironment()
}

func (a *XPU) Close() {
	a.mu.Lock()
	if a.closed {
		a.mu.Unlock()
		return
	}
	a.closed = true
	initialized := a.initialized && a.initErr == nil
	ref := a.resourceRef
	a.mu.Unlock()

	if initialized {
		a.resourceManager.Release(ref)
	}
}

func (a *XPU) getClient() (spb.SystemMonitorServiceClient, error) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.closed {
		return nil, errors.New("monitor: xpu resource is closed")
	}
	if !a.initialized {
		a.initialized = true
		a.client, a.resourceRef, a.initErr = a.resourceManager.Acquire()
	}

	return a.client, a.initErr
}
