package scheduler_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
)

func httpError(status int) error {
	return &graphql.HTTPError{StatusCode: status}
}

func TestClassify(t *testing.T) {
	cases := []struct {
		err  error
		want scheduler.Disposition
	}{
		{scheduler.ErrSweepNotFound, scheduler.DispositionNotFound},
		{fmt.Errorf("wrapped: %w", scheduler.ErrSweepNotFound),
			scheduler.DispositionNotFound},
		{assert.AnError, scheduler.DispositionTransient},
		{context.DeadlineExceeded, scheduler.DispositionTransient},
		{httpError(404), scheduler.DispositionNotFound},
		{httpError(429), scheduler.DispositionRateLimited},
		{httpError(400), scheduler.DispositionFatal},
		{httpError(401), scheduler.DispositionFatal},
		{httpError(403), scheduler.DispositionFatal},
		{httpError(409), scheduler.DispositionFatal},
		{httpError(410), scheduler.DispositionFatal},
		{httpError(413), scheduler.DispositionFatal},
		{httpError(422), scheduler.DispositionFatal},
		{httpError(501), scheduler.DispositionFatal},
		{httpError(408), scheduler.DispositionTransient},
		{httpError(500), scheduler.DispositionTransient},
		{httpError(502), scheduler.DispositionTransient},
		{httpError(503), scheduler.DispositionTransient},
		// The backend client retries an unrecognized 4xx, so the loop
		// keeps polling too and lets its error budget decide.
		{httpError(418), scheduler.DispositionTransient},
	}

	for _, c := range cases {
		t.Run(fmt.Sprintf("%v", c.err), func(t *testing.T) {
			assert.Equal(t, c.want, scheduler.Classify(c.err))
		})
	}
}

func TestBackoffDoublesAndCaps(t *testing.T) {
	backoff := &scheduler.Backoff{}

	var slowdowns []float64
	for range 8 {
		backoff.OnError(scheduler.DispositionTransient)
		slowdowns = append(slowdowns, backoff.Slowdown().Seconds())
	}

	assert.Equal(t,
		[]float64{1, 2, 4, 8, 16, 32, 60, 60},
		slowdowns)
}

func TestBackoffResetsOnSuccess(t *testing.T) {
	backoff := &scheduler.Backoff{}
	backoff.OnError(scheduler.DispositionTransient)
	backoff.OnError(scheduler.DispositionTransient)

	backoff.OnSuccess()

	assert.Equal(t, 0.0, backoff.Slowdown().Seconds())
}

func TestBackoffExhaustedAfterConsecutiveErrors(t *testing.T) {
	backoff := &scheduler.Backoff{}

	count := 0
	for !backoff.Exhausted() {
		backoff.OnError(scheduler.DispositionTransient)
		count++
	}

	assert.Equal(t, 10, count)
}

func TestBackoffRateLimitSlowsButNeverExhausts(t *testing.T) {
	backoff := &scheduler.Backoff{}

	for range 100 {
		backoff.OnError(scheduler.DispositionRateLimited)
	}

	assert.False(t, backoff.Exhausted())
	assert.Equal(t, 60.0, backoff.Slowdown().Seconds())
	// A transient error after rate limits starts the budget fresh.
	backoff.OnError(scheduler.DispositionTransient)
	assert.False(t, backoff.Exhausted())
}
