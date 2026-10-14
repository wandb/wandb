package monitor

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// symonRetryMinDelay is the delay before the first attempt to reopen
	// a subscription whose stream ended or failed to start.
	symonRetryMinDelay = time.Second

	// symonRetryMaxDelay caps the delay between attempts, which doubles
	// after each consecutive failure.
	symonRetryMaxDelay = time.Minute
)

// Symon streams system metrics from the wandb-symon sidecar binary.
//
// The sidecar is started by the first Subscribe or Probe call, not by NewSymon.
// If it exits or its stream ends while subscribed, it is started again and
// the subscription is reopened.
type Symon struct {
	ctx             context.Context
	resourceManager *SymonResourceManager
	resourceRef     SymonResourceManagerRef
	logger          *observability.CoreLogger

	errorReported atomic.Bool

	mu sync.Mutex

	// unsubscribe ends the running Subscribe stream, if any.
	unsubscribe context.CancelFunc
}

// NewSymon returns a Symon resource whose sidecar start and requests are
// canceled together with ctx.
func NewSymon(
	ctx context.Context,
	resourceManager *SymonResourceManager,
	logger *observability.CoreLogger,
) *Symon {
	return &Symon{
		ctx:             ctx,
		resourceManager: resourceManager,
		resourceRef:     resourceManager.Acquire(),
		logger:          logger,
	}
}

// Subscribe passes the samples described by request to publish until
// Unsubscribe or Close is called or the resource's context ends.
//
// publish may block until its context is done, which happens when the
// subscription ends. Subscribing while subscribed does nothing.
func (a *Symon) Subscribe(
	request *spb.SubscribeRequest,
	publish func(context.Context, *spb.SubscribeResponse),
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
	go a.stream(ctx, request, publish)
}

// Unsubscribe ends the subscription, if any. A publish in flight returns
// once its context is done.
func (a *Symon) Unsubscribe() {
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
// after a delay that doubles with each consecutive failure and starts over
// after a stream that outlived the longest delay. The first failure is
// captured; later ones are debug-logged.
func (a *Symon) stream(
	ctx context.Context,
	request *spb.SubscribeRequest,
	publish func(context.Context, *spb.SubscribeResponse),
) {
	delay := symonRetryMinDelay
	for {
		started := time.Now()
		err := a.subscribe(ctx, request, publish)
		if ctx.Err() != nil {
			return
		}
		if time.Since(started) > symonRetryMaxDelay {
			delay = symonRetryMinDelay
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
		delay = min(2*delay, symonRetryMaxDelay)
	}
}

// subscribe opens a stream and passes its samples to publish until the
// stream ends.
func (a *Symon) subscribe(
	ctx context.Context,
	request *spb.SubscribeRequest,
	publish func(context.Context, *spb.SubscribeResponse),
) error {
	client, err := a.resourceManager.Client(ctx, a.resourceRef)
	if err != nil {
		return err
	}

	stream, err := client.Subscribe(ctx, request)
	if err != nil {
		return fmt.Errorf("monitor: symon subscribe failed: %w", err)
	}

	for {
		response, err := stream.Recv()
		if err != nil {
			return fmt.Errorf("monitor: symon stream ended: %w", err)
		}
		publish(ctx, response)
	}
}

// Probe returns the sidecar's static facts about the machine described
// by request, or nil if the sidecar cannot be reached.
func (a *Symon) Probe(
	ctx context.Context,
	request *spb.GetMetadataRequest,
) *spb.EnvironmentRecord {
	if a == nil {
		return nil
	}
	client, err := a.resourceManager.Client(ctx, a.resourceRef)
	if err != nil {
		return nil
	}

	e, err := client.GetMetadata(ctx, request)
	if err != nil {
		return nil
	}
	return e.GetRecord().GetEnvironment()
}

// Close ends the subscription and releases the sidecar reference.
func (a *Symon) Close() {
	if a == nil {
		return
	}
	a.Unsubscribe()
	a.resourceManager.Release(a.resourceRef)
}
