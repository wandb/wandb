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
		{httpError(404), DispositionNotFound},
		{httpError(429), DispositionRateLimited},

		// Everything the loop cannot name is fatal: the HTTP client has
		// already spent its retries by the time the error arrives.
		{assert.AnError, DispositionFatal},
		{context.DeadlineExceeded, DispositionFatal},
		{httpError(400), DispositionFatal},
		{httpError(401), DispositionFatal},
		{httpError(403), DispositionFatal},
		{httpError(409), DispositionFatal},
		{httpError(418), DispositionFatal},
		{httpError(500), DispositionFatal},
		{httpError(503), DispositionFatal},

		// A GraphQL-level error (permissions, validation) means the
		// server answered, so it is fatal even though it carries no
		// HTTP status.
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
func checkRetry(t *testing.T, status int) bool {
	t.Helper()

	ctx := withSchedulerRetryPolicy(context.Background())
	assert.NotNil(t, ctx.Value(clients.CtxRetryPolicyKey))

	retry, _ := clients.CheckRetry(ctx, &http.Response{StatusCode: status}, nil)
	return retry
}

func TestSchedulerRetryPolicyLeavesRateLimitsToTheLoop(t *testing.T) {
	// The step's own backoff is the retry, and only an unretried 429
	// reaches Classify with a status to slow down on.
	assert.False(t, checkRetry(t, http.StatusTooManyRequests))
}

func TestSchedulerRetryPolicyRetriesWhatTheSharedClientWould(t *testing.T) {
	for _, status := range []int{
		http.StatusInternalServerError, // 500
		http.StatusBadGateway,          // 502
		http.StatusServiceUnavailable,  // 503
	} {
		assert.True(t, checkRetry(t, status),
			"status %d should still be retried by the HTTP client", status)
	}

	for _, status := range []int{
		http.StatusBadRequest,   // 400
		http.StatusUnauthorized, // 401
		http.StatusForbidden,    // 403
		http.StatusNotFound,     // 404
	} {
		assert.False(t, checkRetry(t, status),
			"status %d can never succeed on a retry", status)
	}
}

func TestBackoffDoublesAndCaps(t *testing.T) {
	backoff := &Backoff{}

	var slowdowns []float64
	for range 8 {
		backoff.OnError()
		slowdowns = append(slowdowns, backoff.Slowdown().Seconds())
	}

	assert.Equal(t,
		[]float64{1, 2, 4, 8, 16, 32, 60, 60},
		slowdowns)
}

func TestBackoffResetsOnSuccess(t *testing.T) {
	backoff := &Backoff{}
	backoff.OnError()
	backoff.OnError()

	backoff.OnSuccess()

	assert.Equal(t, 0.0, backoff.Slowdown().Seconds())
}
