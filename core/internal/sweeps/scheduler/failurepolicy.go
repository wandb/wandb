package scheduler

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/clients"
)

// Disposition is what the scheduler loop should do about a failed API call.
type Disposition int

const (
	// DispositionTransient may clear up on its own; keep polling, but
	// less often.
	DispositionTransient Disposition = iota

	// DispositionRateLimited means the server asked us to slow down;
	// poll less often.
	DispositionRateLimited

	// DispositionFatal means the call will never succeed; end the loop.
	DispositionFatal

	// DispositionNotFound means the sweep is gone; end the loop.
	DispositionNotFound
)

// Classify decides what the scheduler loop should do about an error from
// a W&B API call.
//
// Callers must check for context cancellation first: a cancelled call
// means shutdown, not failure.
func Classify(err error) Disposition {
	// A deleted sweep answers 200 with a null sweep rather than 404,
	// so this is the signal that it is gone.
	if errors.Is(err, ErrSweepNotFound) {
		return DispositionNotFound
	}

	if errors.Is(err, context.DeadlineExceeded) {
		// A timed-out request got no response; the error budget
		// decides when to give up.
		return DispositionTransient
	}

	httpError, ok := errors.AsType[*graphql.HTTPError](err)
	if !ok {
		// No HTTP status means the call never got a response. The HTTP
		// client already retried, so let the error budget end the loop.
		return DispositionTransient
	}

	status := httpError.StatusCode
	switch {
	case status == http.StatusNotFound:
		return DispositionNotFound
	case status == http.StatusTooManyRequests:
		return DispositionRateLimited
	case clients.RetryableStatus(status):
		// The backend client retried; polling later is the only retry
		// left.
		return DispositionTransient
	default:
		// A status the client never retries will not start succeeding
		// because the loop polls again.
		return DispositionFatal
	}
}

const (
	// initialSlowdown is the first delay added to the poll interval
	// after an error.
	initialSlowdown = time.Second

	// maxSlowdown caps the delay added to the poll interval.
	maxSlowdown = 60 * time.Second

	// maxConsecutiveErrors is how many transient failures in a row the
	// loop tolerates before giving up.
	maxConsecutiveErrors = 10
)

// Backoff spaces polls out after failures.
//
// Failed calls are never retried in place — the backend client already
// retried them — the loop just polls less often until a call succeeds.
type Backoff struct {
	slowdown    time.Duration
	consecutive int
}

// Slowdown is the extra delay to add to the poll interval.
func (b *Backoff) Slowdown() time.Duration {
	return b.slowdown
}

// OnSuccess resets the slowdown after a successful poll.
func (b *Backoff) OnSuccess() {
	b.slowdown = 0
	b.consecutive = 0
}

// OnError doubles the slowdown. A rate limit slows polling without
// counting toward Exhausted: obliging the server is not a failure.
func (b *Backoff) OnError(disposition Disposition) {
	b.slowdown = min(max(2*b.slowdown, initialSlowdown), maxSlowdown)

	if disposition == DispositionRateLimited {
		return
	}
	b.consecutive++
}

// Exhausted reports whether so many calls failed in a row that the loop
// should give up.
func (b *Backoff) Exhausted() bool {
	return b.consecutive >= maxConsecutiveErrors
}

// trackedAPI wraps SweepAPI so every call's outcome feeds the backoff
// in one place; no call site records success or failure itself.
//
// A call that failed because ctx was cancelled is not recorded:
// cancellation means shutdown, not backend failure.
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
		a.backoff.OnError(Classify(err))
		return
	}
	a.backoff.OnSuccess()
}

// Slowdown is the extra delay to add to the poll interval.
func (a *trackedAPI) Slowdown() time.Duration {
	return a.backoff.Slowdown()
}

// Exhausted reports whether so many calls failed in a row that the loop
// should give up.
func (a *trackedAPI) Exhausted() bool {
	return a.backoff.Exhausted()
}

func (a *trackedAPI) FetchSweep(ctx context.Context) (*SweepFacts, error) {
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
	page, err := a.api.PollPage(ctx, pageSize, cursor, metricKey)
	a.record(ctx, err)
	return page, err
}

func (a *trackedAPI) ConfirmRunExists(
	ctx context.Context,
	runName string,
) (bool, error) {
	exists, err := a.api.ConfirmRunExists(ctx, runName)
	a.record(ctx, err)
	return exists, err
}

func (a *trackedAPI) EnqueueRun(
	ctx context.Context,
	sweepNodeID string,
	configWireJSON string,
) (string, error) {
	mintedID, err := a.api.EnqueueRun(ctx, sweepNodeID, configWireJSON)
	a.record(ctx, err)
	return mintedID, err
}

func (a *trackedAPI) StopRun(
	ctx context.Context,
	storageID string,
) (bool, error) {
	stopped, err := a.api.StopRun(ctx, storageID)
	a.record(ctx, err)
	return stopped, err
}

func (a *trackedAPI) UpsertSweepState(
	ctx context.Context,
	sweepNodeID string,
	state string,
) error {
	err := a.api.UpsertSweepState(ctx, sweepNodeID, state)
	a.record(ctx, err)
	return err
}
