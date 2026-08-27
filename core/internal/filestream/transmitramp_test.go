package filestream

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/featurechecker"
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
		FeatureProvider: featurechecker.NewPreloaded(nil),
		Logger:          observability.NewNoOpLogger(),
		Printer:         observability.NewPrinter(0),
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

			// The limiter stays at the steady-state interval until the
			// run's first user-visible data starts the ramp.
			assert.Equal(
				t,
				rate.Every(test.wantTarget),
				fs.transmitRateLimit.Limit(),
			)
		})
	}
}

func TestStreamUpdate_RunDataStartsRamp(t *testing.T) {
	factory := FileStreamFactory{
		FeatureProvider: featurechecker.NewPreloaded(nil),
		Logger:          observability.NewNoOpLogger(),
		Printer:         observability.NewPrinter(0),
	}
	fs := factory.New(
		nil,
		context.Background(),
		0,
		time.Minute,
		30*time.Second,
	).(*fileStream)

	fs.StreamUpdate(&HistoryUpdate{})

	assert.Equal(t, rate.Every(30*time.Second), fs.transmitRateLimit.Limit())
}

func TestStreamUpdate_AutomaticUpdatesDontStartRamp(t *testing.T) {
	factory := FileStreamFactory{
		FeatureProvider: featurechecker.NewPreloaded(nil),
		Logger:          observability.NewNoOpLogger(),
		Printer:         observability.NewPrinter(0),
	}
	fs := factory.New(
		nil,
		context.Background(),
		0,
		time.Minute,
		30*time.Second,
	).(*fileStream)

	fs.StreamUpdate(&StatsUpdate{})
	fs.StreamUpdate(&FilesUploadedUpdate{})

	assert.Equal(t, rate.Every(time.Minute), fs.transmitRateLimit.Limit())
}

func TestStartsTransmitRamp(t *testing.T) {
	tests := []struct {
		name   string
		update Update
		want   bool
	}{
		{"history", &HistoryUpdate{}, true},
		{"summary", &SummaryUpdate{}, true},
		{"console logs", &LogsUpdate{}, true},
		{"system metrics", &StatsUpdate{}, false},
		{"files uploaded", &FilesUploadedUpdate{}, false},
		{"preempting", &PreemptingUpdate{}, false},
		{"exit", &ExitUpdate{}, false},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			assert.Equal(t, test.want, startsTransmitRamp(test.update))
		})
	}
}

func TestStartTransmitRamp_ReachesTargetExactly(t *testing.T) {
	// A target that's not a power-of-two multiple of the initial interval
	// must be reached exactly, not overshot.
	initial := time.Millisecond
	target := 5 * time.Millisecond
	limiter := rate.NewLimiter(rate.Every(target), 1)

	startTransmitRamp(context.Background(), limiter, initial, target)

	assert.Equal(t, rate.Every(initial), limiter.Limit())
	assert.Eventually(
		t,
		func() bool { return limiter.Limit() == rate.Every(target) },
		time.Second,
		time.Millisecond,
	)
}

func TestStartTransmitRamp_StopsOnContextDone(t *testing.T) {
	initial := time.Hour
	target := 2 * time.Hour
	limiter := rate.NewLimiter(rate.Every(target), 1)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	startTransmitRamp(ctx, limiter, initial, target)

	// The limiter is sped up to the initial interval, but the ramp stops
	// before slowing it back down.
	assert.Equal(t, rate.Every(initial), limiter.Limit())
}

func TestStartTransmitRamp_NoOpIfInitialNotLessThanTarget(t *testing.T) {
	interval := time.Hour
	limiter := rate.NewLimiter(rate.Every(interval), 1)

	startTransmitRamp(context.Background(), limiter, interval, interval)

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
