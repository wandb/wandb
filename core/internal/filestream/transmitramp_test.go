package filestream

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"golang.org/x/time/rate"
)

func TestRampTransmitRateLimit_ReachesTarget(t *testing.T) {
	initial := time.Millisecond
	target := 8 * time.Millisecond
	limiter := rate.NewLimiter(rate.Every(initial), 1)

	rampTransmitRateLimit(context.Background(), limiter, initial, target)

	assert.Equal(t, rate.Every(target), limiter.Limit())
}

func TestRampTransmitRateLimit_NeverExceedsTarget(t *testing.T) {
	// A target that's not a power-of-two multiple of the initial interval
	// must be reached exactly, not overshot.
	initial := time.Millisecond
	target := 5 * time.Millisecond
	limiter := rate.NewLimiter(rate.Every(initial), 1)

	rampTransmitRateLimit(context.Background(), limiter, initial, target)

	assert.Equal(t, rate.Every(target), limiter.Limit())
}

func TestRampTransmitRateLimit_StopsOnContextDone(t *testing.T) {
	initial := time.Hour
	limiter := rate.NewLimiter(rate.Every(initial), 1)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	rampTransmitRateLimit(ctx, limiter, initial, 2*time.Hour)

	assert.Equal(t, rate.Every(initial), limiter.Limit())
}

func TestRampTransmitRateLimit_NoOpIfInitialNotLessThanTarget(t *testing.T) {
	interval := time.Hour
	limiter := rate.NewLimiter(rate.Every(interval), 1)

	rampTransmitRateLimit(context.Background(), limiter, interval, interval)

	assert.Equal(t, rate.Every(interval), limiter.Limit())
}
