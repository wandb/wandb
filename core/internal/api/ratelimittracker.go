package api

import (
	"fmt"
	"sync"
	"sync/atomic"
	"time"
)

type RateLimitTracker struct {
	minPerSecond float64
	maxPerSecond float64
	smoothing    float64
	minWindow    uint64

	// Estimate of how many requests we're making per quota unit.
	//
	// The backend's RateLimit-Remaining responses use an opaque unit that we
	// must convert to a number of requests.
	//
	// We estimate this by tracking the difference between consecutive
	// RateLimit-Remaining values and the number of requests that happen
	// in-between (in case the server does not send the header on every
	// response). We then compute a moving average.
	requestsPerUnit float64

	// Target number of quota units per second.
	targetUnitsPerSec float64

	// Most recent value of the RateLimit-Remaining header.
	lastRemaining float64

	// Most recent quota window reset time.
	lastInvalidTime time.Time

	// Number of requests we've made since the recorded header values.
	requestsSinceLast atomic.Uint64

	mu *sync.Mutex
}

type RateLimitTrackerParams struct {
	// Minimum rate limit in requests per second.
	MinPerSecond float64

	// Maximum rate limit in requests per second.
	MaxPerSecond float64

	// Smoothing factor in range [0, 1).
	//
	// The closer this is to 0, the faster the rate is updated based on
	// response headers.
	Smoothing float64

	// Minimum number of requests in an estimation window.
	//
	// Setting above 1 causes optimal rate limit estimates to be averaged out
	// over more requests.
	MinRequestsForEstimate uint64
}

func NewRateLimitTracker(params RateLimitTrackerParams) *RateLimitTracker {
	if params.Smoothing < 0 || params.Smoothing >= 1 {
		panic(fmt.Sprintf("api: bad rate limit smoothing: %v", params.Smoothing))
	}

	return &RateLimitTracker{
		mu: &sync.Mutex{},

		minPerSecond: params.MinPerSecond,
		maxPerSecond: params.MaxPerSecond,
		smoothing:    params.Smoothing,
		minWindow:    max(1, params.MinRequestsForEstimate),

		// Initialize to our maximum rate limit.
		requestsPerUnit:   1,
		targetUnitsPerSec: params.MaxPerSecond,
	}
}

// Returns the current estimated target rate limit.
func (tracker *RateLimitTracker) TargetRateLimit() float64 {
	tracker.mu.Lock()
	defer tracker.mu.Unlock()

	reqPerSecond := tracker.requestsPerUnit * tracker.targetUnitsPerSec
	return min(max(reqPerSecond, tracker.minPerSecond), tracker.maxPerSecond)
}

// Registers that we're about to make a request.
func (tracker *RateLimitTracker) TrackRequest() {
	tracker.requestsSinceLast.Add(1)
}

// Updates the target rate limit using RateLimit header values.
//
// - t: the current time
// - rlRemaining: the RateLimit-Remaining header
// - rlReset: the RateLimit-Reset header
func (tracker *RateLimitTracker) UpdateEstimates(
	t time.Time,
	rlHeader RateLimitHeaders,
) {
	// Too little time left in the quota window, so we can't accurately
	// approximate a rate.
	if rlHeader.Reset <= 1 {
		return
	}

	tracker.mu.Lock()
	defer tracker.mu.Unlock()

	window, ok := tracker.tryStartNewWindow(t, rlHeader)
	if !ok {
		return
	}

	tracker.targetUnitsPerSec = window.targetUnitsPerSec

	if window.quotaConsumed < 1 || window.isNewQuotaWindow {
		// If the quota didn't change (or increased), then we can raise our
		// rate limit, i.e. raise our estimate of how many requests we can
		// make per quota unit.
		//
		// We also do this if we're in a new quota window to guard against
		// the possibility of our rate limit being so slow that every request
		// lands in a new quota window.
		//
		// We push the conversion factor (reqs / unit) toward the value
		// satisfying
		//   (reqs / unit) * (target units / sec) = (max reqs / sec)
		tracker.requestsPerUnit = tracker.interp(
			tracker.requestsPerUnit,
			tracker.maxPerSecond/window.targetUnitsPerSec,
		)
	} else {
		// Otherwise, update our requestsPerUnit estimate normally.
		tracker.requestsPerUnit = tracker.interp(
			tracker.requestsPerUnit,
			float64(window.nRequests)/window.quotaConsumed,
		)
	}
}

// Interpolate from old to new using the smoothing factor.
func (tracker *RateLimitTracker) interp(old float64, new float64) float64 {
	// This just results in an exponential moving average.
	return old*tracker.smoothing + new*(1-tracker.smoothing)
}

// Statistics from an estimation window.
type rateLimitStats struct {
	// Number of requests made.
	nRequests uint64

	// Decrease in RateLimit-Remaining header, if `isNewWindow` is false.
	quotaConsumed float64

	// Rate limit based on the final Remaining and Reset values.
	targetUnitsPerSec float64

	// Whether the quota window reset during the last estimation window.
	isNewQuotaWindow bool
}

// Opens a new estimation window.
//
// If a new window opens, the second return value is true and the first
// return value contains stats for the window.
//
// Otherwise, the second return value is false.
func (tracker *RateLimitTracker) tryStartNewWindow(
	t time.Time,
	rlHeader RateLimitHeaders,
) (rateLimitStats, bool) {
	nRequests := tracker.requestsSinceLast.Swap(0)

	// Not enough requests made for a good estimate, so don't start a new
	// estimation window.
	if t.Before(tracker.lastInvalidTime) && nRequests < tracker.minWindow {
		tracker.requestsSinceLast.Add(nRequests)
		return rateLimitStats{}, false
	}

	lastRemaining := tracker.lastRemaining
	lastInvalidTime := tracker.lastInvalidTime
	tracker.lastRemaining = rlHeader.Remaining
	tracker.lastInvalidTime = t.Add(time.Duration(rlHeader.Reset) * time.Second)

	return rateLimitStats{
		nRequests:         nRequests,
		isNewQuotaWindow:  t.After(lastInvalidTime),
		quotaConsumed:     lastRemaining - rlHeader.Remaining,
		targetUnitsPerSec: rlHeader.Remaining / rlHeader.Reset,
	}, true
}
