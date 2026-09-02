package scheduler

import (
	"context"
	"fmt"
	"net/http"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/vektah/gqlparser/v2/gqlerror"

	"github.com/wandb/wandb/core/internal/clients"
)

func httpError(status int) error {
	return &graphql.HTTPError{StatusCode: status}
}

func gqlErrors(errs ...*gqlerror.Error) error {
	return gqlerror.List(errs)
}

func TestClassify(t *testing.T) {
	cases := []struct {
		err  error
		want Disposition
	}{
		{ErrSweepNotFound, DispositionNotFound},
		{fmt.Errorf("wrapped: %w", ErrSweepNotFound), DispositionNotFound},
		{assert.AnError, DispositionTransient},
		{context.DeadlineExceeded, DispositionTransient},
		{httpError(404), DispositionNotFound},
		{httpError(429), DispositionRateLimited},
		{httpError(400), DispositionFatal},
		{httpError(401), DispositionFatal},
		{httpError(403), DispositionFatal},
		{httpError(409), DispositionFatal},
		{httpError(410), DispositionFatal},
		{httpError(413), DispositionFatal},
		{httpError(422), DispositionFatal},
		{httpError(501), DispositionFatal},
		{httpError(408), DispositionTransient},
		{httpError(500), DispositionTransient},
		{httpError(502), DispositionTransient},
		{httpError(503), DispositionTransient},
		// An unrecognized 4xx may still clear up, so the loop keeps
		// polling and lets its error budget decide.
		{httpError(418), DispositionTransient},

		// A GraphQL-level error (permissions, validation) means the
		// server answered, so it is Fatal rather than Transient even
		// though it carries no HTTP status.
		{gqlErrors(&gqlerror.Error{Message: "permission denied"}),
			DispositionFatal},
		{fmt.Errorf("wrapped: %w", gqlErrors(&gqlerror.Error{Message: "bad input"})),
			DispositionFatal},
		// The most restrictive Disposition among the list wins.
		{gqlErrors(
			&gqlerror.Error{Message: "a"},
			&gqlerror.Error{Message: "b", Err: httpError(404)},
		), DispositionNotFound},
		{gqlErrors(
			&gqlerror.Error{Message: "a", Err: httpError(429)},
			&gqlerror.Error{Message: "b"},
		), DispositionFatal},
	}

	for _, c := range cases {
		t.Run(fmt.Sprintf("%v", c.err), func(t *testing.T) {
			assert.Equal(t, c.want, Classify(c.err))
		})
	}
}

// checkRetry runs the shared client's retry policy the way the HTTP client
// would, on a context carrying the scheduler's policy.
//
// It fails if clients.CheckRetry does not pick the policy up: the value
// has to have the plain function type CheckRetry type-asserts against.
func checkRetry(t *testing.T, resp *http.Response, err error) bool {
	t.Helper()

	ctx := withSchedulerRetryPolicy(context.Background())
	assert.NotNil(t, ctx.Value(clients.CtxRetryPolicyKey))

	retry, _ := clients.CheckRetry(ctx, resp, err)
	return retry
}

func TestSchedulerRetryPolicyLeavesStatusesToClassify(t *testing.T) {
	for _, status := range []int{
		http.StatusTooManyRequests,     // 429
		http.StatusInternalServerError, // 500
		http.StatusBadGateway,          // 502
		http.StatusServiceUnavailable,  // 503
		http.StatusNotFound,            // 404
	} {
		resp := &http.Response{StatusCode: status}

		assert.False(t, checkRetry(t, resp, nil),
			"status %d should reach Classify instead of being retried",
			status)
	}
}

func TestSchedulerRetryPolicyRetriesTransportErrors(t *testing.T) {
	// A request that got no response carries no status to classify, so
	// the shared client still retries it.
	assert.True(t, checkRetry(t, nil, assert.AnError))
}

func TestSchedulerRetryPolicyStopsOnCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(
		withSchedulerRetryPolicy(context.Background()))
	cancel()

	retry, _ := clients.CheckRetry(ctx, &http.Response{StatusCode: 500}, nil)

	assert.False(t, retry)
}

func TestBackoffDoublesAndCaps(t *testing.T) {
	backoff := &Backoff{}

	var slowdowns []float64
	for range 8 {
		backoff.OnError(DispositionTransient)
		slowdowns = append(slowdowns, backoff.Slowdown().Seconds())
	}

	assert.Equal(t,
		[]float64{1, 2, 4, 8, 16, 32, 60, 60},
		slowdowns)
}

func TestBackoffResetsOnSuccess(t *testing.T) {
	backoff := &Backoff{}
	backoff.OnError(DispositionTransient)
	backoff.OnError(DispositionTransient)

	backoff.OnSuccess()

	assert.Equal(t, 0.0, backoff.Slowdown().Seconds())
}

func TestBackoffExhaustedAfterConsecutiveErrors(t *testing.T) {
	backoff := &Backoff{}

	count := 0
	for !backoff.Exhausted() {
		backoff.OnError(DispositionTransient)
		count++
	}

	assert.Equal(t, 10, count)
}

func TestBackoffRateLimitSlowsButNeverExhausts(t *testing.T) {
	backoff := &Backoff{}

	for range 100 {
		backoff.OnError(DispositionRateLimited)
	}

	assert.False(t, backoff.Exhausted())
	assert.Equal(t, 60.0, backoff.Slowdown().Seconds())
	// A transient error after rate limits starts the budget fresh.
	backoff.OnError(DispositionTransient)
	assert.False(t, backoff.Exhausted())
}
