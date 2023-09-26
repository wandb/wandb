package debounce

import (
	"context"
	"fmt"

	"golang.org/x/time/rate"
)

type Debouncer struct {
	ctx       context.Context
	cancel    context.CancelFunc
	limiter   *rate.Limiter
	tokenChan chan struct{}
}

func NewDebouncer(eventRate rate.Limit, burstSize int) *Debouncer {
	ctx, cancel := context.WithCancel(context.Background())
	return &Debouncer{
		ctx:       ctx,
		cancel:    cancel,
		limiter:   rate.NewLimiter(eventRate, burstSize),
		tokenChan: make(chan struct{}),
	}
}

func (d *Debouncer) Close() {
	d.cancel()
}

func (d *Debouncer) Trigger() {
	select {
	// todo: verify that this is actually non-blocking :)
	case d.tokenChan <- struct{}{}:
		// Triggered
	default:
		// Channel is full, do not trigger, it'll send the update when it can
		fmt.Println("Dropping message")
	}
}

func (d *Debouncer) Debounce(f func()) {
	for {
		select {
		case <-d.ctx.Done():
			fmt.Println("Context done, sending last request")
			f()
			return
		case <-d.tokenChan:
			// Wait for the next opportunity to send a request
			err := d.limiter.Wait(d.ctx)
			if err != nil {
				fmt.Println("Error waiting:", err)
				continue
			}

			// Send the request
			fmt.Println("Sending request")
			f()
		}
	}
}
