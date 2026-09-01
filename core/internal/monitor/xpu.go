package monitor

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// XPUManager manages access to the shared wandb-xpu sidecar.
type XPUManager interface {
	// Acquire starts the sidecar if it is not running and registers a
	// reference to it. It aborts early with an error if ctx is canceled.
	Acquire(ctx context.Context) (spb.SystemMonitorServiceClient, XPUResourceManagerRef, error)

	// Release unregisters a reference returned by Acquire, stopping the
	// sidecar once no references remain.
	Release(XPUResourceManagerRef)
}

// ErrXPUInitReported wraps a sidecar startup error that Sample already
// returned once, letting the monitoring loop log repeats at debug level
// (see ShouldCaptureSamplingError) instead of capturing each one.
var ErrXPUInitReported = errors.New("wandb-xpu startup failure already reported")

var errXPUClosed = errors.New("monitor: xpu resource is closed")

// maxXPUInitAttempts bounds how many times a startup attempt that was cut
// short by a caller's deadline or by shutdown may be retried before the
// failure is cached for the lifetime of the resource.
const maxXPUInitAttempts = 3

type xpuInitState int

const (
	xpuInitNotStarted xpuInitState = iota
	xpuInitInFlight
	xpuInitDone
)

// XPU monitors GPUs (Nvidia, AMD, Apple) and Google TPUs via the
// wandb-xpu sidecar binary.
//
// The sidecar is started lazily by the first Sample or Probe call.
type XPU struct {
	resourceManager XPUManager

	pid          int32
	gpuDeviceIds []int32

	mu           sync.Mutex
	closed       bool
	initState    xpuInitState
	initDone     chan struct{} // closed when the in-flight attempt finishes
	initAttempts int
	client       spb.SystemMonitorServiceClient
	resourceRef  XPUResourceManagerRef
	initErr      error

	initErrReported atomic.Bool
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
	ctx, cancel := context.WithTimeout(context.Background(), defaultSamplingInterval)
	defer cancel()

	client, err := a.getClient(ctx)
	if err != nil {
		if a.initErrReported.Swap(true) {
			return nil, fmt.Errorf("%w: %v", ErrXPUInitReported, err)
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
// Close never blocks on an in-flight startup attempt: if one is running,
// it observes the closed flag when it finishes and releases the
// reference itself (see getClient).
func (a *XPU) Close() {
	a.mu.Lock()
	if a.closed {
		a.mu.Unlock()
		return
	}
	a.closed = true
	state := a.initState
	ref := a.resourceRef
	err := a.initErr
	a.mu.Unlock()

	if state == xpuInitDone && err == nil {
		a.resourceManager.Release(ref)
	}
}

// getClient returns the sidecar client, starting the sidecar on first use.
//
// The manager's Acquire call runs without holding a.mu so that Probe,
// Sample, and Close never stall behind a slow startup. If an attempt is
// cut short by ctx (e.g. the run is shutting down or the sampling
// deadline expired), a later call may retry it, up to maxXPUInitAttempts
// times; any other failure is cached for the lifetime of the resource.
func (a *XPU) getClient(ctx context.Context) (spb.SystemMonitorServiceClient, error) {
	for {
		a.mu.Lock()

		switch {
		case a.closed:
			a.mu.Unlock()
			return nil, errXPUClosed

		case a.initState == xpuInitDone:
			client, err := a.client, a.initErr
			a.mu.Unlock()
			return client, err

		case a.initState == xpuInitInFlight:
			done := a.initDone
			a.mu.Unlock()

			select {
			case <-done:
				// Re-check the state: the attempt may have failed in a
				// retryable way, in which case this call starts its own.
			case <-ctx.Done():
				return nil, ctx.Err()
			}

		default: // xpuInitNotStarted
			a.initState = xpuInitInFlight
			a.initAttempts++
			done := make(chan struct{})
			a.initDone = done
			a.mu.Unlock()

			client, ref, err := a.resourceManager.Acquire(ctx)

			a.mu.Lock()
			switch {
			case a.closed:
				a.initState = xpuInitDone
				a.initErr = errXPUClosed
				a.mu.Unlock()
				close(done)

				// Closed while acquiring: hand the reference back.
				if err == nil {
					a.resourceManager.Release(ref)
				}
				return nil, errXPUClosed

			case err != nil && ctx.Err() != nil && a.initAttempts < maxXPUInitAttempts:
				// The attempt was interrupted rather than failing
				// outright; let a later call retry it.
				a.initState = xpuInitNotStarted
				a.mu.Unlock()
				close(done)
				return nil, err

			default:
				a.initState = xpuInitDone
				a.client, a.resourceRef, a.initErr = client, ref, err
				a.mu.Unlock()
				close(done)
				return client, err
			}
		}
	}
}
