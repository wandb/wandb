package filestream

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/observability"
)

func TestFileStreamFactory_TransmitIntervals(t *testing.T) {
	tests := []struct {
		name        string
		initial     time.Duration
		target      time.Duration
		wantInitial time.Duration
		wantTarget  time.Duration
	}{
		{
			name:        "defaults",
			wantInitial: defaultInitialTransmitInterval,
			wantTarget:  defaultTransmitInterval,
		},
		{
			name:        "configured",
			initial:     3 * time.Second,
			target:      10 * time.Second,
			wantInitial: 3 * time.Second,
			wantTarget:  10 * time.Second,
		},
		{
			name:        "default initial capped at target",
			target:      time.Second,
			wantInitial: time.Second,
			wantTarget:  time.Second,
		},
		{
			name:        "configured initial capped at target",
			initial:     20 * time.Second,
			target:      10 * time.Second,
			wantInitial: 10 * time.Second,
			wantTarget:  10 * time.Second,
		},
	}

	factory := FileStreamFactory{
		Logger:  observability.NewNoOpLogger(),
		Printer: observability.NewPrinter(0),
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fs := factory.New(
				nil,
				context.Background(),
				0,
				test.target,
				test.initial,
			).(*fileStream)

			assert.Equal(t, test.wantInitial, fs.initialTransmitInterval)
			assert.Equal(t, test.wantTarget, fs.transmitInterval)
			assert.Equal(
				t,
				rate.Every(test.wantInitial),
				fs.transmitRateLimit.Limit(),
			)
		})
	}
}

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

func TestNextTransmitInterval(t *testing.T) {
	maxDuration := time.Duration(1<<63 - 1)
	tests := []struct {
		name     string
		interval time.Duration
		target   time.Duration
		want     time.Duration
	}{
		{"doubles", time.Second, 8 * time.Second, 2 * time.Second},
		{"reaches exact target", 4 * time.Second, 8 * time.Second, 8 * time.Second},
		{"caps below target", 4 * time.Second, 5 * time.Second, 5 * time.Second},
		{
			"does not overflow",
			maxDuration/2 + 1,
			maxDuration,
			maxDuration,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			assert.Equal(
				t,
				test.want,
				nextTransmitInterval(test.interval, test.target),
			)
		})
	}
}
