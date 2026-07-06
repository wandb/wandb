package filestream

import (
	"context"
	"time"

	"golang.org/x/time/rate"
)

// rampTransmitRateLimit gradually slows the limiter from the initial to the
// target transmit interval, doubling the interval each time it elapses.
//
// The limiter's interval is expected to start at initial, so that a run's
// first batches of data reach the backend (and the UI) quickly before
// transmissions decay to the steady-state interval.
//
// It returns once the target interval is reached or ctx is done. It is a
// no-op if initial is not less than target.
func rampTransmitRateLimit(
	ctx context.Context,
	limiter *rate.Limiter,
	initial time.Duration,
	target time.Duration,
) {
	for interval := initial; interval < target; {
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
		}

		interval = min(2*interval, target)
		limiter.SetLimit(rate.Every(interval))
	}
}
