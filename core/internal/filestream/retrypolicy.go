package filestream

import (
	"context"
	"net/http"
	"time"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
)

// DefaultUnmarked404RetryDeadline is how long a filestream request retries
// an unbroken run of 404s that lack the server's response-origin header.
//
// It is meant to outlast a load balancer or ingress outage, while bounding
// how long a real 404 that lost its header keeps a run retrying. It applies
// only to these 404s; every other retried failure keeps the filestream retry
// budget.
//
// The value is a judgment call, not a measured limit. A longer deadline rides
// out longer outages, but in the bad case costs more: the filestream backoff
// waits at most DefaultRetryWaitMax between attempts, so a run sends about
// 120 requests in 2 hours, and finishing the run waits for the deadline.
const DefaultUnmarked404RetryDeadline = 2 * time.Hour

// RetryPolicy is the retry policy for filestream requests.
//
// It is clients.RetryMostFailures, except that a request whose context was
// prepared by withUnmarked404Retry also retries 404s without the
// api.ServerHeader header, for up to a deadline.
//
// The W&B server marks every response with that header. A 404 without it
// likely came from a load balancer, ingress or proxy in front of the server,
// for example while the server is unreachable, and not from the server saying
// the run doesn't exist. A marked 404 still stops uploads.
//
// This is only used for filestream: other clients share
// clients.RetryMostFailures, and file uploads go to storage that never sends
// the header.
func RetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	if state, ok := ctx.Value(unmarked404RetryKey{}).(*unmarked404Retry); ok {
		if state.shouldRetry(ctx, resp, err) {
			return true, nil
		}
	}

	return clients.RetryMostFailures(ctx, resp, err)
}

// Backoff is the retry backoff for filestream requests.
//
// It is clients.ExponentialBackoffWithJitter, except that after a 404 that
// RetryPolicy retries for lacking the response-origin header, the wait ends
// by that rule's deadline. Without this, a long Retry-After on such a 404
// would keep the request waiting past the deadline, and finishing a run
// waits for it. If the next attempt gets another such 404, RetryPolicy
// stops.
func Backoff(
	minimum, maximum time.Duration,
	attemptNum int,
	resp *http.Response,
) time.Duration {
	wait := clients.ExponentialBackoffWithJitter(
		minimum,
		maximum,
		attemptNum,
		resp,
	)

	if resp == nil || resp.Request == nil {
		return wait
	}

	ctx := resp.Request.Context()
	if state, ok := ctx.Value(unmarked404RetryKey{}).(*unmarked404Retry); ok {
		return state.capWait(wait)
	}

	return wait
}

type unmarked404RetryKey struct{}

// unmarked404Retry tracks the 404s without the response-origin header that a
// single filestream request has received.
//
// It tracks two things separately. The streak is the current unbroken run of
// unmarked 404s, which the deadline measures; any other response ends it. The
// request totals cover every unmarked 404 the request retried, so the
// request's outcome is reported even if another failure, like a 503, came
// between those 404s and the end of the request.
//
// It is used by one request in one goroutine, so it is not lock-protected.
type unmarked404Retry struct {
	deadline time.Duration
	logger   *observability.CoreLogger

	// deferred holds telemetry to record when the filestream finishes.
	deferred *deferredTelemetry

	// streakStart is when the current unbroken run of unmarked 404s began.
	//
	// It is zero if the last response was not an unmarked 404.
	streakStart time.Time

	// streakLength is the number of unmarked 404s in the current run.
	streakLength int

	// firstRetryAt is when the request first retried an unmarked 404.
	//
	// It is zero if the request has not retried one. Other responses
	// don't reset it.
	firstRetryAt time.Time

	// retriedCount is the number of unmarked 404s the request has received.
	retriedCount int
}

// withUnmarked404Retry returns a context in which RetryPolicy retries
// 404s without the response-origin header for up to the deadline.
//
// The deadline is measured from the first such 404 in an unbroken run of
// them. Any other response, like a success or a 503, ends the run.
//
// Telemetry that must wait for the filestream to finish goes to deferred.
func withUnmarked404Retry(
	ctx context.Context,
	deadline time.Duration,
	logger *observability.CoreLogger,
	deferred *deferredTelemetry,
) context.Context {
	return context.WithValue(
		ctx,
		unmarked404RetryKey{},
		&unmarked404Retry{
			deadline: deadline,
			logger:   logger,
			deferred: deferred,
		},
	)
}

// capWait shortens a retry wait so that it ends by the deadline of the
// current run of unmarked 404s, if the last response was one.
func (s *unmarked404Retry) capWait(wait time.Duration) time.Duration {
	if s.streakStart.IsZero() {
		return wait
	}

	remaining := s.deadline - time.Since(s.streakStart)
	return max(0, min(wait, remaining))
}

// shouldRetry reports whether to retry a response because it is an
// unmarked 404 within the deadline.
//
// A false result means the default policy decides.
func (s *unmarked404Retry) shouldRetry(
	ctx context.Context,
	resp *http.Response,
	err error,
) bool {
	isUnmarked404 := err == nil &&
		resp != nil &&
		resp.StatusCode == http.StatusNotFound &&
		!api.HasServerHeader(resp)

	if !isUnmarked404 {
		s.endStreak()
		s.recordOutcome(resp)
		return false
	}

	if ctx.Err() != nil {
		return false
	}

	s.streakLength++
	s.retriedCount++
	if s.streakStart.IsZero() {
		s.startStreak()
		return true
	}

	if time.Since(s.streakStart) >= s.deadline {
		s.recordDeadlineExceeded()
		return false
	}

	return true
}

// startStreak starts a run of unmarked 404s, which starts the deadline.
func (s *unmarked404Retry) startStreak() {
	s.streakStart = time.Now()

	if s.firstRetryAt.IsZero() {
		s.firstRetryAt = s.streakStart
		s.logRetryStarted()
	} else {
		s.logStreakRestarted()
	}
}

// endStreak ends the current run of unmarked 404s, if any, because the
// request got a different response. This restarts the deadline.
func (s *unmarked404Retry) endStreak() {
	s.streakStart = time.Time{}
	s.streakLength = 0
}

// recordOutcome reports how a request that retried unmarked 404s ended,
// if resp ends it.
//
// A success or a 404 from the server ends the request. A nil response is a
// transport error, and other statuses are left to the default policy, which
// retries or stops without an outcome here.
func (s *unmarked404Retry) recordOutcome(resp *http.Response) {
	if s.firstRetryAt.IsZero() || resp == nil {
		return
	}

	switch {
	case resp.StatusCode >= 200 && resp.StatusCode <= 299:
		s.recordRecovered()
	case resp.StatusCode == http.StatusNotFound:
		s.recordStoppedByServer()
	}
}
