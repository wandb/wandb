package monitor

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// xpuRetryMinDelay is the delay before the first attempt to reopen
	// a subscription whose stream ended or failed to start.
	xpuRetryMinDelay = time.Second

	// xpuRetryMaxDelay caps the delay between attempts, which doubles
	// after each consecutive failure.
	xpuRetryMaxDelay = time.Minute
)

// XPU streams system metrics from the wandb-xpu sidecar binary: GPU
// (Nvidia, AMD, Apple) and Google TPU metrics everywhere, and the host's
// CPU, memory, disk and network metrics on Linux.
//
// The sidecar is started by the first Subscribe or Probe call, not by NewXPU.
// If it exits or its stream ends while subscribed, it is started again and
// the subscription is reopened.
type XPU struct {
	ctx             context.Context
	resourceManager *XPUResourceManager
	resourceRef     XPUResourceManagerRef
	logger          *observability.CoreLogger

	// request is the Subscribe request without its interval.
	request *spb.SubscribeRequest

	errorReported atomic.Bool

	mu sync.Mutex

	// unsubscribe ends the running Subscribe stream, if any.
	unsubscribe context.CancelFunc
}

// NewXPU returns an XPU resource whose sidecar start and requests are
// canceled together with ctx.
//
// request describes what to subscribe to; its interval is set by Subscribe.
// shared asks for the wandb-xpu shared by the user's processes on this
// machine instead of a sidecar private to this process.
func NewXPU(
	ctx context.Context,
	resourceManager *XPUResourceManager,
	logger *observability.CoreLogger,
	request *spb.SubscribeRequest,
	shared bool,
) *XPU {
	return &XPU{
		ctx:             ctx,
		resourceManager: resourceManager,
		resourceRef: resourceManager.Acquire(
			XPUResourceOptions{Shared: shared, Logger: logger},
		),
		logger:  logger,
		request: request,
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
	if a.unsubscribe != nil {
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
// A stream that ends or fails to start for any other reason is reopened
// after a delay that doubles with each consecutive failure. The first
// failure is captured; later ones are debug-logged.
func (a *XPU) stream(
	ctx context.Context,
	interval time.Duration,
	publish func(context.Context, *spb.StatsRecord),
) {
	delay := xpuRetryMinDelay
	for {
		delivered, err := a.subscribe(ctx, interval, publish)
		if ctx.Err() != nil {
			return
		}
		if delivered {
			delay = xpuRetryMinDelay
		}

		if a.errorReported.Swap(true) {
			a.logger.Debug(err.Error())
		} else {
			a.logger.CaptureError("monitor", err)
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(delay):
		}
		delay = min(2*delay, xpuRetryMaxDelay)
	}
}

// subscribe opens a stream and passes its samples to publish until the
// stream ends, reporting whether it delivered any.
func (a *XPU) subscribe(
	ctx context.Context,
	interval time.Duration,
	publish func(context.Context, *spb.StatsRecord),
) (bool, error) {
	client, err := a.resourceManager.Client(ctx, a.resourceRef)
	if err != nil {
		return false, err
	}

	request := proto.Clone(a.request).(*spb.SubscribeRequest)
	request.IntervalSeconds = interval.Seconds()
	stream, err := client.Subscribe(ctx, request)
	if err != nil {
		return false, fmt.Errorf("monitor: xpu subscribe failed: %w", err)
	}

	delivered := false
	for {
		response, err := stream.Recv()
		if err != nil {
			return delivered, fmt.Errorf("monitor: xpu stream ended: %w", err)
		}
		delivered = true
		publish(ctx, response.GetRecord().GetStats())
	}
}

func (a *XPU) Probe(ctx context.Context) *spb.EnvironmentRecord {
	if a == nil {
		return nil
	}
	client, err := a.resourceManager.Client(ctx, a.resourceRef)
	if err != nil {
		return nil
	}

	e, err := client.GetMetadata(ctx, &spb.GetMetadataRequest{
		DiskPaths: a.request.GetDiskPaths(),
	})
	if err != nil {
		return nil
	}
	return e.GetRecord().GetEnvironment()
}

// Close ends the subscription and releases the sidecar reference.
func (a *XPU) Close() {
	if a == nil {
		return
	}
	a.Unsubscribe()
	a.resourceManager.Release(a.resourceRef)
}
