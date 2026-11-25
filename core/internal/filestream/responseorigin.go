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

type unmarked404RetryKey struct{}

// unmarked404Retry tracks the 404s without the response-origin header that a
// single filestream request has received.
//
// It is used by one request in one goroutine, so it is not lock-protected.
type unmarked404Retry struct {
	deadline time.Duration
	logger   *observability.CoreLogger

	// streakStart is when the current unbroken run of unmarked 404s began.
	//
	// It is zero if the last response was not an unmarked 404.
	streakStart time.Time

	// streakLength is the number of unmarked 404s in the current run.
	streakLength int
}

// withUnmarked404Retry returns a context in which RetryPolicy retries
// 404s without the response-origin header for up to the deadline.
//
// The deadline is measured from the first such 404 in an unbroken run of
// them. Any other response, like a success or a 503, ends the run.
func withUnmarked404Retry(
	ctx context.Context,
	deadline time.Duration,
	logger *observability.CoreLogger,
) context.Context {
	return context.WithValue(
		ctx,
		unmarked404RetryKey{},
		&unmarked404Retry{deadline: deadline, logger: logger},
	)
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
		s.endStreak(resp)
		return false
	}

	if ctx.Err() != nil {
		return false
	}

	s.streakLength++
	if s.streakStart.IsZero() {
		s.streakStart = time.Now()
		s.recordRetryStarted()
		return true
	}

	if time.Since(s.streakStart) >= s.deadline {
		s.recordDeadlineExceeded()
		return false
	}

	return true
}

// endStreak ends the current run of unmarked 404s, if any, because the
// request got a different response.
//
// A nil response means a transport error, which the default policy retries.
func (s *unmarked404Retry) endStreak(resp *http.Response) {
	if s.streakStart.IsZero() {
		return
	}

	switch {
	case resp == nil:
	case resp.StatusCode >= 200 && resp.StatusCode <= 299:
		s.recordRecovered()
	case resp.StatusCode == http.StatusNotFound:
		s.recordStoppedByServer()
	}

	s.streakStart = time.Time{}
	s.streakLength = 0
}
