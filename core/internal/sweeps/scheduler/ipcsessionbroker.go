package scheduler

import (
	"context"
	"errors"
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ErrAlreadyScheduled is returned when a sweep is already scheduled.
var ErrAlreadyScheduled = errors.New(
	"scheduler: this sweep already has a running scheduler in this" +
		" wandb-core process; stop it before starting another")

// TaskResolverFactory builds the resolver for a new scheduler session.
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

	// bySweep maps sweep ids to session ids.
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

// NewIPCSessionBroker creates a new IPCSessionBroker.
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
// connCtx is the creating connection's lifetime — the session dies
// with its client — and reqCtx bounds the init's own network calls.
func (b *IPCSessionBroker) InitScheduler(
	connCtx context.Context,
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
) (*spb.SweepSchedulerServerInitResponse, error) {
	sweepKey := fmt.Sprintf(
		"%s/%s/%s", req.Entity, req.Project, req.SweepId)

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
// tasks. NextTask already released every finished session, so the only
// case left to filter out is a dead client's cancelled context.
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
		// The id predates this process: wandb-core restarted.
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
// The session is kept so a later poll still finds the cached terminal
// task. The id check stops a dead session's late Done from freeing the
// sweep of the successor that replaced it.
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
// Sessions observe it through their contexts; there are no scheduler
// goroutines to wait for.
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
