package scheduler

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// telemetryShutdownTimeout bounds flushing a session's telemetry on exit.
const telemetryShutdownTimeout = 5 * time.Second

// errSessionFinished is the cancel cause of a session that reached its
// terminal task.
var errSessionFinished = errors.New("scheduler: session finished")

// ErrAlreadyScheduled is returned when a sweep is already scheduled.
var ErrAlreadyScheduled = errors.New(
	"scheduler: this sweep already has a running scheduler in this" +
		" wandb-core process; stop it before starting another")

// TaskResolverFactory builds the resolver for a new scheduler session
// over the API the broker opened for the session's sweep.
type TaskResolverFactory func(
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
	sweepAPI SweepAPI,
	logger *observability.CoreLogger,
) (TaskResolver, *spb.SweepSchedulerServerInitResponse, error)

var _ TaskResolverFactory = NewTaskResolver

// NewTaskResolver is the TaskResolverFactory the session broker uses
// to start scheduler sessions.
func NewTaskResolver(
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
	sweepAPI SweepAPI,
	logger *observability.CoreLogger,
) (TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
	if err := sweepAPI.CheckLocalSchedulerSupported(reqCtx); err != nil {
		return nil, nil, err
	}

	facts, err := sweepAPI.FetchSweep(reqCtx)
	if err != nil {
		return nil, nil, err
	}

	cfg, err := parseSweepConfig(facts.Config)
	if err != nil {
		return nil, nil, err
	}
	metricKeys, err := objectiveMetricKeys(req.GetObjectives())
	if err != nil {
		return nil, nil, err
	}

	scheduler := NewScheduler(SchedulerParams{
		API:          sweepAPI,
		Logger:       logger,
		SweepNodeID:  facts.NodeID,
		MetricKeys:   metricKeys,
		BatchSize:    int(req.BatchSize),
		RunCap:       cfg.RunCap,
		PollInterval: secondsToDuration(req.PollIntervalSeconds),
	})

	return scheduler, &spb.SweepSchedulerServerInitResponse{
		SweepConfig:       facts.Config,
		DisplayName:       facts.DisplayName,
		ControllerRunName: facts.ControllerRunName,
	}, nil
}

// IPCSessionBroker tracks the scheduler sessions of one server process.
type IPCSessionBroker struct {
	mu sync.Mutex

	nextID   int
	factory  TaskResolverFactory
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
func NewIPCSessionBroker(factory TaskResolverFactory) *IPCSessionBroker {
	return &IPCSessionBroker{
		factory:  factory,
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

	cancelAndRespond := func(err error) (*spb.SweepSchedulerServerInitResponse, error) {
		cancel(err)
		return nil, err
	}

	logger, err := newLoggerFromRequestSettings(schedCtx, req)
	if err != nil {
		return cancelAndRespond(err)
	}

	// The session's own API: it talks to the backend the client's
	// settings name, with the client's credentials.
	sweepAPI, err := newSweepAPIFromSettings(req, logger)
	if err != nil {
		return cancelAndRespond(err)
	}

	resolver, response, err := b.factory(reqCtx, req, sweepAPI, logger)
	if err != nil {
		return cancelAndRespond(err)
	}

	b.mu.Lock()
	defer b.mu.Unlock()

	if b.liveSessionLocked(sweepKey) != nil {
		// A concurrent init for the same sweep won the race.
		slog.Warn(
			"scheduler: init rejected, sweep already has a live scheduler",
			"sweep", sweepKey)
		return cancelAndRespond(ErrAlreadyScheduled)
	}

	id := fmt.Sprintf("scheduler-%d", b.nextID)
	b.nextID++
	s := &session{
		id:       id,
		sweepKey: sweepKey,
		machine: newSchedulerStateMachine(
			resolver,
			logger.With([]any{"id", id, "sweep", sweepKey}, nil),
		),
		ctx:    schedCtx,
		cancel: cancel,
	}
	b.sessions[id] = s
	b.bySweep[sweepKey] = id

	// stop and drop the session on connection cancel
	context.AfterFunc(schedCtx, func() { b.dropOnClose(s) })

	slog.Info(
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
		slog.Warn(
			"scheduler: init rejected, sweep already has a live scheduler",
			"sweep", sweepKey)
		return ErrAlreadyScheduled
	}
	return nil
}

// liveSessionLocked returns the sweep's session if it can still serve
// tasks. Finished and abandoned sessions are dropped
// Callers must hold mu.
func (b *IPCSessionBroker) liveSessionLocked(sweepKey string) *session {
	id, ok := b.bySweep[sweepKey]
	if !ok {
		return nil
	}

	// drop removes both entries at once, so the mapped session exists.
	s := b.sessions[id]
	if s.ctx.Err() != nil {
		return nil
	}
	return s
}

// NextTask reports the previous task's result and blocks for the next
// task, up to about one poll interval.
//
// ctx is the poll's own lifetime. The session is under a different ctx
func (b *IPCSessionBroker) NextTask(
	ctx context.Context,
	req *spb.SweepSchedulerClientNextTaskRequest,
) *spb.SweepSchedulerServerNextTaskResponse {
	s := b.lookup(req.SessionId)
	if s == nil {
		// The id predates this process: wandb-core restarted.
		slog.Warn(
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

	response := s.machine.NextTask(ctx, req.Result)
	if response == nil {
		return nil
	}

	if done := response.GetDone(); done != nil {
		b.release(s, done)
	}
	return response
}

// release retires a session that reached its terminal task:
func (b *IPCSessionBroker) release(
	s *session,
	done *spb.SweepSchedulerServerDoneTask,
) {
	if b.drop(s) {
		slog.Info(
			"scheduler: session finished",
			"id", s.id,
			"sweep", s.sweepKey,
			"reason", done.Reason.String())
	}
	s.cancel(errSessionFinished)
}

// dropOnClose retires a session whose client's connection ended before
// the session reached a terminal task.
func (b *IPCSessionBroker) dropOnClose(s *session) {
	s.machine.Stop()

	if b.drop(s) {
		slog.Debug(
			"scheduler: session dropped, its client is gone",
			"id", s.id,
			"sweep", s.sweepKey)
	}
}

// drop forgets s and reports whether it was still tracked.
func (b *IPCSessionBroker) drop(s *session) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.dropLocked(s)
}

// dropLocked forgets s and reports whether it was still tracked.
//
// The identity checks stop a session that is retiring late from
// evicting the successor that replaced it.
//
// Callers must hold mu.
func (b *IPCSessionBroker) dropLocked(s *session) bool {
	if b.sessions[s.id] != s {
		return false
	}
	delete(b.sessions, s.id)

	if b.bySweep[s.sweepKey] == s.id {
		delete(b.bySweep, s.sweepKey)
	}

	return true
}

// Stop asks a session to finish its current step and stop.
//
// Stopping an unknown or already-finished session has no effect: the
// request is fire-and-forget, so there is nothing to report an error to.
func (b *IPCSessionBroker) Stop(req *spb.SweepSchedulerClientStopRequest) {
	s := b.lookup(req.SessionId)
	if s == nil {
		slog.Debug(
			"scheduler: stop for unknown scheduler id",
			"id", req.SessionId)
		return
	}

	slog.Info("scheduler: stop requested", "id", req.SessionId)
	s.machine.Stop()
}

func (b *IPCSessionBroker) lookup(id string) *session {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.sessions[id]
}

// newLoggerFromRequestSettings builds the session's logger, exporting
// telemetry through a proxy that is shut down when ctx ends.
func newLoggerFromRequestSettings(
	ctx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
) (*observability.CoreLogger, error) {
	if req.Settings == nil {
		return nil, fmt.Errorf("scheduler: the init request carries no settings")
	}
	s := settings.From(req.Settings)

	telemetryProxy := analytics.NewOpenTelemetryProxy(
		context.Background(), s, "wandb-core")
	context.AfterFunc(ctx, func() {
		shutdownCtx, cancel := context.WithTimeout(
			context.Background(), telemetryShutdownTimeout)
		defer cancel()
		if err := telemetryProxy.Shutdown(shutdownCtx); err != nil {
			slog.Debug("scheduler: telemetry shutdown failed", "error", err)
		}
	})

	telemetryTags := observability.Tags{
		"base_url":  s.GetBaseURL(),
		"sweep_url": s.GetSweepURL(),
	}

	telemetryRecorder := analytics.NewTelemetryRecorder(
		telemetryProxy,
		analytics.NewTelemetryContext(),
	)

	return observability.NewCoreLogger(
		slog.Default(),
		telemetryRecorder,
	).With(nil, telemetryTags), nil
}
