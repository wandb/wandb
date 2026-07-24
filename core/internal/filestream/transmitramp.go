package filestream

import (
	"context"
	"time"

	"golang.org/x/time/rate"
)

// startsTransmitRamp reports whether the update carries user-visible run
// data whose arrival should begin ramping the transmit rate limit.
//
// Only data the user logs counts: history, summary and console logs.
// Automatic traffic like system metrics and file upload notifications
// begins shortly after every run starts, so ramping on it would defeat
// the point of ramping on first data rather than on run start.
func startsTransmitRamp(update Update) bool {
	switch update.(type) {
	case *HistoryUpdate, *SummaryUpdate, *LogsUpdate:
		return true
	default:
		return false
	}
}

// rampTransmitRateLimit speeds the limiter up to the initial transmit
// interval, then gradually slows it back to the target interval, doubling
// the interval each time it elapses.
//
// It is started when a run's first user-visible data arrives, so that the
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
	if initial >= target {
		return
	}

	limiter.SetLimit(rate.Every(initial))

	for interval := initial; interval < target; {
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
		}

		interval = nextTransmitInterval(interval, target)
		limiter.SetLimit(rate.Every(interval))
	}
}

// nextTransmitInterval doubles interval without overflowing, capped at target.
// It requires 0 < interval < target.
func nextTransmitInterval(interval, target time.Duration) time.Duration {
	if interval >= target-interval {
		return target
	}
	return 2 * interval
}
