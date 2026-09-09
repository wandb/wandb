package scheduler

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/vektah/gqlparser/v2/gqlerror"

	"github.com/wandb/wandb/core/internal/clients"
)

// Disposition is what the scheduler loop should do about a failed API call.
//
// Values are ordered least to most restrictive, so the errors of one
// GraphQL response can be combined by taking the maximum.
type Disposition int

const (
	// DispositionRateLimited means the server asked us to slow down;
	// poll less often.
	DispositionRateLimited Disposition = iota

	// DispositionFatal means the call will never succeed; end the loop.
	DispositionFatal

	// DispositionNotFound means the sweep is gone; end the loop.
	DispositionNotFound
)

// Classify decides what the scheduler loop should do about an error from
// a W&B API call, after the underlying HTTP client has retried.
func Classify(err error) Disposition {
	if errors.Is(err, ErrSweepNotFound) {
		return DispositionNotFound
	}

	// genqlient returns the response body's "errors" array directly as a
	// gqlerror.List when the server answers with GraphQL-level errors
	if gqlErrs, ok := errors.AsType[gqlerror.List](err); ok && len(gqlErrs) > 0 {
		return classifyGQLErrors(gqlErrs)
	}

	httpError, ok := errors.AsType[*graphql.HTTPError](err)
	if !ok {
		return DispositionFatal
	}

	switch httpError.StatusCode {
	case http.StatusNotFound:
		return DispositionNotFound
	case http.StatusTooManyRequests:
		return DispositionRateLimited
	default:
		return DispositionFatal
	}
}

// schedulerRetryPolicy hands a rate limit back to the loop instead of
// retrying it, and retries everything else the way the shared client
// does.
//
// The step is the retry: it already spaces its next call out by a
// doubling slowdown, which is what the server asked for.
//
// The shared client only consults this for a response it actually got:
// transport errors and cancellations never reach it.
func schedulerRetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	if resp.StatusCode == http.StatusTooManyRequests {
		return false, nil
	}
	return clients.RetryMostFailures(ctx, resp, err)
}

// withSchedulerRetryPolicy applies schedulerRetryPolicy to the requests
// made with the returned context.
func withSchedulerRetryPolicy(ctx context.Context) context.Context {
	return context.WithValue(
		ctx,
		clients.CtxRetryPolicyKey,
		schedulerRetryPolicy,
	)
}

func classifyGQLErrors(errs gqlerror.List) Disposition {
	// A bare GraphQL-level error defaults to Fatal
	result := DispositionFatal
	for _, gqlErr := range errs {
		if gqlErr == nil || gqlErr.Err == nil {
			continue
		}
		if d := Classify(gqlErr.Err); d > result {
			result = d
		}
	}
	return result
}

const (
	// initialSlowdown is the first delay added to the poll interval
	// after an error.
	initialSlowdown = time.Second

	// maxSlowdown caps the delay added to the poll interval.
	maxSlowdown = 60 * time.Second
)

// Backoff spaces polls out after failures.
type Backoff struct {
	slowdown time.Duration
}

// Slowdown is the extra delay to add to the poll interval.
func (b *Backoff) Slowdown() time.Duration {
	return b.slowdown
}

// OnSuccess resets the slowdown after a successful poll.
func (b *Backoff) OnSuccess() {
	b.slowdown = 0
}

// OnError doubles the delay the next poll waits, up to maxSlowdown.
func (b *Backoff) OnError() {
	b.slowdown = min(max(2*b.slowdown, initialSlowdown), maxSlowdown)
}

// trackedAPI wraps SweepAPI with Backoff
type trackedAPI struct {
	api     *SweepAPI
	backoff Backoff
}

func newTrackedAPI(api *SweepAPI) *trackedAPI {
	return &trackedAPI{api: api}
}

// record feeds one call's outcome into the backoff.
func (a *trackedAPI) record(ctx context.Context, err error) {
	if errors.Is(ctx.Err(), context.Canceled) {
		return
	}

	if err != nil {
		a.backoff.OnError()
		return
	}
	a.backoff.OnSuccess()
}

// Slowdown is the extra delay to add to the poll interval.
func (a *trackedAPI) Slowdown() time.Duration {
	return a.backoff.Slowdown()
}

func (a *trackedAPI) FetchSweep(ctx context.Context) (*SweepFacts, error) {
	ctx = withSchedulerRetryPolicy(ctx)
	facts, err := a.api.FetchSweep(ctx)
	a.record(ctx, err)
	return facts, err
}

func (a *trackedAPI) PollPage(
	ctx context.Context,
	pageSize int,
	cursor *string,
	metricKey string,
) (*PollPage, error) {
	ctx = withSchedulerRetryPolicy(ctx)
	page, err := a.api.PollPage(ctx, pageSize, cursor, metricKey)
	a.record(ctx, err)
	return page, err
}

func (a *trackedAPI) ConfirmRunExists(
	ctx context.Context,
	runName string,
) (bool, error) {
	ctx = withSchedulerRetryPolicy(ctx)
	exists, err := a.api.ConfirmRunExists(ctx, runName)
	a.record(ctx, err)
	return exists, err
}

func (a *trackedAPI) EnqueueRun(
	ctx context.Context,
	sweepNodeID string,
	configWireJSON string,
) (string, error) {
	ctx = withSchedulerRetryPolicy(ctx)
	mintedID, err := a.api.EnqueueRun(ctx, sweepNodeID, configWireJSON)
	a.record(ctx, err)
	return mintedID, err
}

func (a *trackedAPI) StopRun(
	ctx context.Context,
	storageID string,
) (bool, error) {
	ctx = withSchedulerRetryPolicy(ctx)
	stopped, err := a.api.StopRun(ctx, storageID)
	a.record(ctx, err)
	return stopped, err
}

func (a *trackedAPI) UpsertSweepState(
	ctx context.Context,
	sweepNodeID string,
	state string,
) error {
	ctx = withSchedulerRetryPolicy(ctx)
	err := a.api.UpsertSweepState(ctx, sweepNodeID, state)
	a.record(ctx, err)
	return err
}
