package monitor

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var errXPUClosed = errors.New("monitor: xpu resource is closed")

// XPU streams GPU (Nvidia, AMD, Apple) and Google TPU metrics from the
// wandb-xpu sidecar binary.
//
// The sidecar is started by the first Subscribe or Probe call, not by NewXPU.
type XPU struct {
	ctx             context.Context
	resourceManager *XPUResourceManager
	logger          *observability.CoreLogger

	pid          int32
	gpuDeviceIds []int32

	startOnce        sync.Once
	startErrReported atomic.Bool

	mu          sync.Mutex
	closed      bool
	client      spb.SystemMonitorServiceClient
	resourceRef XPUResourceManagerRef
	startErr    error

	// unsubscribe ends the running Subscribe stream, if any.
	unsubscribe context.CancelFunc
}

// NewXPU returns an XPU resource whose sidecar start and requests are
// canceled together with ctx.
func NewXPU(
	ctx context.Context,
	resourceManager *XPUResourceManager,
	logger *observability.CoreLogger,
	pid int32,
	gpuDeviceIds []int32,
) *XPU {
	return &XPU{
		ctx:             ctx,
		resourceManager: resourceManager,
		logger:          logger,
		pid:             pid,
		gpuDeviceIds:    gpuDeviceIds,
	}
}

// Subscribe passes metrics sampled every interval to publish until
// Unsubscribe or Close is called or the resource's context ends.
//
// publish may block until its context is done, which happens when the
// subscription ends. Subscribing while subscribed does nothing.
func (a *XPU) Subscribe(
	interval time.Duration,
	publish func(context.Context, *spb.StatsRecord),
) {
	if a == nil {
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.closed || a.unsubscribe != nil {
		return
	}

	ctx, cancel := context.WithCancel(a.ctx)
	a.unsubscribe = cancel
	go a.stream(ctx, interval, publish)
}

// Unsubscribe ends the subscription, if any. A publish in flight returns
// once its context is done.
func (a *XPU) Unsubscribe() {
	if a == nil {
		return
	}
	a.mu.Lock()
	cancel := a.unsubscribe
	a.unsubscribe = nil
	a.mu.Unlock()

	if cancel != nil {
		cancel()
	}
}

// stream passes the sidecar's samples to publish until ctx ends.
//
// A sidecar start failure is reported once; later subscriptions do nothing.
func (a *XPU) stream(
	ctx context.Context,
	interval time.Duration,
	publish func(context.Context, *spb.StatsRecord),
) {
	// The resource's context bounds the start, so that a subscription that
	// ends during it does not leave the sidecar failed for good.
	client, err := a.getClient(a.ctx)
	if err != nil {
		if !errors.Is(err, errXPUClosed) && !a.startErrReported.Swap(true) {
			a.logError(err)
		}
		return
	}

	stream, err := client.Subscribe(ctx, &spb.SubscribeRequest{
		IntervalSeconds: interval.Seconds(),
		Pid:             a.pid,
		GpuDeviceIds:    a.gpuDeviceIds,
	})
	for err == nil {
		var response *spb.SubscribeResponse
		response, err = stream.Recv()
		if err == nil {
			publish(ctx, response.GetRecord().GetStats())
		}
	}
	a.logError(fmt.Errorf("monitor: xpu stream ended: %w", err))
}

// logError captures an unexpected error and debug-logs an expected one,
// such as the stream ending because the subscription was canceled.
func (a *XPU) logError(err error) {
	if ShouldCaptureSamplingError(err) {
		a.logger.CaptureError("monitor", err)
	} else {
		a.logger.Debug(fmt.Sprintf("monitor: benign xpu error: %v", err))
	}
}

func (a *XPU) Probe(ctx context.Context) *spb.EnvironmentRecord {
	if a == nil {
		return nil
	}
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

// Close ends the subscription and releases the sidecar reference if one
// was acquired.
//
// Close does not wait for a start that is still in progress; getClient
// hands the reference back when that start completes.
func (a *XPU) Close() {
	if a == nil {
		return
	}
	a.Unsubscribe()

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
