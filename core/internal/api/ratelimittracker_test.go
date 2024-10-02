package api_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/api"
)

func TestInitialRateLimit(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond: 1,
		MaxPerSecond: 10,
	})

	assert.EqualValues(t, 10, rl.TargetRateLimit())
}

func TestUpdate_NoSmoothing_FindsOptimalRate(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond:           0.01,
		MaxPerSecond:           10,
		Smoothing:              0,
		MinRequestsForEstimate: 1,
	})

	rl.UpdateEstimates(
		time.Time{},
		api.RateLimitHeaders{Remaining: 20, Reset: 8})
	rl.TrackRequest()
	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(2*time.Second),
		api.RateLimitHeaders{Remaining: 12, Reset: 6})

	// 2 requests used 8 quota, so 1 request = 4 quota
	// There is 12 quota left, so we can make 3 more requests in 6 seconds.
	assert.EqualValues(t, 0.5, rl.TargetRateLimit())
}

func TestUpdate_MinRequestsForEstimate(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond:           0.01,
		MaxPerSecond:           10,
		Smoothing:              0,
		MinRequestsForEstimate: 2,
	})

	rl.UpdateEstimates(
		time.Time{},
		api.RateLimitHeaders{Remaining: 20, Reset: 7})
	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(time.Second),
		api.RateLimitHeaders{Remaining: 15, Reset: 6})

	// After only 1 request, the estimate remains at its initial value.
	assert.EqualValues(t, 10, rl.TargetRateLimit())

	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(2*time.Second),
		api.RateLimitHeaders{Remaining: 10, Reset: 5})

	// Once we have 2 requests, the estimate is updated.
	assert.EqualValues(t, 0.4, rl.TargetRateLimit())

	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(3*time.Second),
		api.RateLimitHeaders{Remaining: 5, Reset: 4})

	// Once again, only one request does not update the estimate.
	assert.EqualValues(t, 0.4, rl.TargetRateLimit())
}

func TestUpdate_Smoothing(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond:           0.01,
		MaxPerSecond:           11,
		Smoothing:              0.5,
		MinRequestsForEstimate: 1,
	})

	estimates := []float64{}

	rl.UpdateEstimates(
		time.Time{},
		api.RateLimitHeaders{Remaining: 50, Reset: 10})

	for i := 1; i <= 9; i++ {
		rl.TrackRequest()
		rl.UpdateEstimates(
			time.Time{}.Add(time.Second),
			api.RateLimitHeaders{
				Remaining: 50 - float64(i)*5,
				Reset:     10 - float64(i),
			},
		)

		estimates = append(estimates, rl.TargetRateLimit())
	}

	assert.IsNonIncreasing(t, estimates)

	// The optimal rate is 1.0 at each step:
	//   - 1 request uses 5 quota
	//   - The remaining quota is 5 times the remaining time
	// The estimates should approach the optimal rate.
	assert.InDelta(t, 1.0, estimates[len(estimates)-1], 0.05)
}

func TestUpdate_OneSecondLeft(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond:           0.01,
		MaxPerSecond:           10,
		Smoothing:              0,
		MinRequestsForEstimate: 1,
	})

	rl.UpdateEstimates(
		time.Time{},
		api.RateLimitHeaders{Remaining: 6, Reset: 2})
	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(time.Second),
		api.RateLimitHeaders{Remaining: 5, Reset: 1})

	// Since only one second remains before the quota resets, we don't update
	// the limit to avoid incorrect numbers.
	assert.EqualValues(t, 10, rl.TargetRateLimit())
}

func TestUpdate_NoQuotaChange_RaisesLimit(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond:           0.01,
		MaxPerSecond:           10,
		Smoothing:              0,
		MinRequestsForEstimate: 1,
	})

	rl.UpdateEstimates(
		time.Time{},
		api.RateLimitHeaders{Remaining: 15, Reset: 6})
	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(time.Second),
		api.RateLimitHeaders{Remaining: 10, Reset: 5})
	assert.EqualValues(t, 0.4, rl.TargetRateLimit())

	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(2*time.Second),
		api.RateLimitHeaders{Remaining: 10, Reset: 4})

	assert.EqualValues(t, 10, rl.TargetRateLimit())
}

func TestUpdate_NewQuotaWindow_RaisesLimit(t *testing.T) {
	rl := api.NewRateLimitTracker(api.RateLimitTrackerParams{
		MinPerSecond:           0.01,
		MaxPerSecond:           10,
		Smoothing:              0,
		MinRequestsForEstimate: 1,
	})

	rl.UpdateEstimates(
		time.Time{},
		api.RateLimitHeaders{Remaining: 15, Reset: 6})
	rl.TrackRequest()
	rl.TrackRequest()
	rl.UpdateEstimates(
		time.Time{}.Add(time.Second),
		api.RateLimitHeaders{Remaining: 10, Reset: 5})
	assert.EqualValues(t, 0.8, rl.TargetRateLimit())

	// Simulate the quota resetting.
	rl.UpdateEstimates(
		time.Time{}.Add(7*time.Second),
		api.RateLimitHeaders{Remaining: 5, Reset: 10})

	// We increase the limit toward the max because we can't estimate how much
	// quota a request consumes based on the delta (10 => 9999).
	//
	// The intention is that if requests are rate-limited so much that each
	// request lands in a new quota window, we eventually raise the limit
	// instead of getting stuck.
	assert.EqualValues(t, 10, rl.TargetRateLimit())
}
