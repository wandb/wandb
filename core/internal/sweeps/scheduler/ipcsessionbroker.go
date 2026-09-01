package scheduler

import (
	"context"
	"errors"
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ErrAlreadyScheduled rejects an init for a sweep that already has a
// live scheduler in this process.
//
// The message travels verbatim to the rejected client's terminal.
var ErrAlreadyScheduled = errors.New(
	"scheduler: this sweep already has a running scheduler in this" +
		" wandb-core process; stop it before starting another")

// TaskResolverFactory builds the resolver for a new scheduler session.
//
// schedCtx spans the session; reqCtx bounds the init request's network
// calls. The returned response's id field is filled in by the broker.
type TaskResolverFactory func(
	schedCtx context.Context,
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
) (TaskResolver, *spb.SweepSchedulerServerInitResponse, error)

// IPCSessionBroker tracks the scheduler sessions of one server process.
type IPCSessionBroker struct {
	mu sync.Mutex

	nextID   int
	factory  TaskResolverFactory
	logger   *observability.CoreLogger
	sessions map[string]*session

	// bySweep indexes sessions by sweep so a second init for the same
	// sweep is rejected while the first is live instead of racing it.
	bySweep map[string]string
}

// session is one scheduler bound to the connection that created it.
type session struct {
	id       string
	sweepKey string
	machine  *schedulerStateMachine

	// ctx is the session's lifetime; it ends with the creating
	// connection, so liveness checks see a dead client's session.
	ctx    context.Context
	cancel context.CancelCauseFunc
}

func NewIPCSessionBroker(
	factory TaskResolverFactory,
	logger *observability.CoreLogger,
) *IPCSessionBroker {
	return &IPCSessionBroker{
		factory:  factory,
		logger:   logger,
		sessions: make(map[string]*session),
		bySweep:  make(map[string]string),
	}
}

// InitScheduler starts a scheduler session for a sweep.
//
// Returns ErrAlreadyScheduled while this process has a live session for
// the same sweep: concurrent schedulers would race each other's polls
// and enqueues. A session whose loop finished or whose client's
// connection died does not block a new one, so a scheduler can be rerun
// without restarting wandb-core. connCtx is the creating connection's
// lifetime context — the session dies with its client — and reqCtx
// bounds the init's own network calls.
func (b *IPCSessionBroker) InitScheduler(
	connCtx context.Context,
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
) (*spb.SweepSchedulerServerInitResponse, error) {
	sweepKey := fmt.Sprintf(
		"%s/%s/%s", req.Entity, req.Project, req.SweepId)

	// Reject before the factory's network calls; re-checked under the
	// same lock that inserts, in case a concurrent init wins the race.
	if err := b.checkNotScheduled(sweepKey); err != nil {
		return nil, err
	}

	schedCtx, cancel := context.WithCancelCause(connCtx)

	resolver, response, err := b.factory(schedCtx, reqCtx, req)
	if err != nil {
		b.logger.Error(
			"scheduler: init failed",
			"sweep", sweepKey,
			"error", err)
		cancel(err)
		return nil, err
	}

	b.mu.Lock()
	defer b.mu.Unlock()

	if b.liveSessionLocked(sweepKey) != nil {
		// A concurrent init for the same sweep won the race.
		b.logger.Warn(
			"scheduler: init rejected, sweep already has a live scheduler",
			"sweep", sweepKey)
		cancel(ErrAlreadyScheduled)
		return nil, ErrAlreadyScheduled
	}

	id := fmt.Sprintf("scheduler-%d", b.nextID)
	b.nextID++
	b.sessions[id] = &session{
		id:       id,
		sweepKey: sweepKey,
		machine: newSchedulerStateMachine(
			schedCtx,
			resolver,
			b.logger.With([]any{"id", id, "sweep", sweepKey}, nil),
		),
		ctx:    schedCtx,
		cancel: cancel,
	}
	b.bySweep[sweepKey] = id

	b.logger.Info(
		"scheduler: session started",
		"id", id,
		"sweep", sweepKey)

	response.SessionId = id
	return response, nil
}

// checkNotScheduled returns ErrAlreadyScheduled if the sweep has a live
// session.
func (b *IPCSessionBroker) checkNotScheduled(sweepKey string) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.liveSessionLocked(sweepKey) != nil {
		b.logger.Warn(
			"scheduler: init rejected, sweep already has a live scheduler",
			"sweep", sweepKey)
		return ErrAlreadyScheduled
	}
	return nil
}

// liveSessionLocked returns the sweep's session if it can still serve
// tasks. A finished session is not here — NextTask releases the sweep
// when it delivers the terminal task — so only a dead client's session
// remains to filter out through its cancelled context.
//
// Callers must hold mu.
func (b *IPCSessionBroker) liveSessionLocked(sweepKey string) *session {
	id, ok := b.bySweep[sweepKey]
	if !ok {
		return nil
	}

	s := b.sessions[id]
	if s.ctx.Err() != nil {
		return nil
	}
	return s
}

// NextTask reports the previous task's result and blocks for the next
// task, up to about one poll interval.
func (b *IPCSessionBroker) NextTask(
	req *spb.SweepSchedulerClientNextTaskRequest,
) *spb.SweepSchedulerServerNextTaskResponse {
	s := b.lookup(req.SessionId)
	if s == nil {
		// The id predates this process: wandb-core restarted since the
		// scheduler was initialized.
		b.logger.Warn(
			"scheduler: poll for unknown scheduler id",
			"id", req.SessionId)
		return &spb.SweepSchedulerServerNextTaskResponse{
			Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
				Done: &spb.SweepSchedulerServerDoneTask{
					Reason: spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
					Message: "unknown scheduler id; wandb-core may have " +
						"restarted. Rerun the scheduler to resume the sweep.",
				},
			},
		}
	}

	response := s.machine.NextTask(req.Result)
	if done := response.GetDone(); done != nil {
		b.release(s, done)
	}
	return response
}

// release frees the sweep for a new scheduler once s is finished.
//
// The session itself is kept so redelivered polls still find the cached
// terminal task. The id check matters when a dead client's session was
// already replaced: its late Done must not free the successor's sweep.
func (b *IPCSessionBroker) release(
	s *session,
	done *spb.SweepSchedulerServerDoneTask,
) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.bySweep[s.sweepKey] == s.id {
		delete(b.bySweep, s.sweepKey)
		b.logger.Info(
			"scheduler: session finished",
			"id", s.id,
			"sweep", s.sweepKey,
			"reason", done.Reason.String())
	}
}

// Stop asks a session to finish its current step and stop.
//
// Stopping an unknown or already-finished session has no effect: the
// request is fire-and-forget, so there is nothing to report an error to.
func (b *IPCSessionBroker) Stop(req *spb.SweepSchedulerClientStopRequest) {
	s := b.lookup(req.SessionId)
	if s == nil {
		b.logger.Debug(
			"scheduler: stop for unknown scheduler id",
			"id", req.SessionId)
		return
	}

	b.logger.Info("scheduler: stop requested", "id", req.SessionId)
	s.machine.Stop()
}

// Shutdown cancels every session because the server is exiting.
//
// Sessions observe the cancellation through their contexts; there are no
// scheduler goroutines to wait for.
func (b *IPCSessionBroker) Shutdown() {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.logger.Info(
		"scheduler: cancelling all sessions for server shutdown",
		"count", len(b.sessions))
	for _, s := range b.sessions {
		s.cancel(context.Canceled)
	}
}

func (b *IPCSessionBroker) lookup(id string) *session {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.sessions[id]
}
