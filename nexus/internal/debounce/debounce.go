package debounce

import (
	"context"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"golang.org/x/time/rate"
)

type Debouncer struct {
	once      sync.Once
	ctx       context.Context
	cancel    context.CancelFunc
	limiter   *rate.Limiter
	tokenChan chan struct{}
	logger    *observability.NexusLogger
	wg        *sync.WaitGroup
}

func NewDebouncer(eventRate rate.Limit, burstSize int, logger *observability.NexusLogger) *Debouncer {
	ctx, cancel := context.WithCancel(context.Background())
	return &Debouncer{
		ctx:       ctx,
		cancel:    cancel,
		limiter:   rate.NewLimiter(eventRate, burstSize),
		tokenChan: make(chan struct{}, 1),
		logger:    logger,
		wg:        &sync.WaitGroup{},
	}
}

func (d *Debouncer) Close() {
	d.once.Do(func() {
		d.cancel()
		d.wg.Wait()
	})
}

func (d *Debouncer) Trigger() {
	select {
	// todo: verify that this is actually non-blocking :)
	case d.tokenChan <- struct{}{}:
		// Triggered
	default:
		// Channel is full, do not trigger, it'll send the update when it can
		d.logger.Debug("Debouncer channel is full, not triggering")
	}
}

func (d *Debouncer) Start(f func()) {
	d.wg.Add(1)
	go func() {
	outer:
		for {
			select {
			case <-d.ctx.Done():
				d.logger.Debug("Context done, sending last request")
				f()
				break outer
			case <-d.tokenChan:
				// Wait for the next opportunity to send a request
				err := d.limiter.Wait(d.ctx)
				if err != nil {
					d.logger.Debug("Error waiting for limiter", err)
					continue
				}
				// Send the request
				d.logger.Debug("Sending request")
				f()
			}
		}
		d.wg.Done()
	}()
}
