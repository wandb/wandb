package scheduler

import (
	"context"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Clock abstracts time so tests can control it directly instead of
// waiting on real timers and grace periods.
type Clock interface {
	// Now is the current time.
	Now() time.Time

	// NewTimer starts a timer that fires once after d, and returns a
	// function to release its resources; callers must call it even if
	// the timer already fired.
	NewTimer(d time.Duration) (<-chan time.Time, func())
}

// RealClock is the production Clock.
type RealClock struct{}

func (RealClock) Now() time.Time { return time.Now() }

func (RealClock) NewTimer(d time.Duration) (<-chan time.Time, func()) {
	timer := time.NewTimer(d)
	return timer.C, func() { timer.Stop() }
}

// SchedulerParams configures a new Scheduler.
type SchedulerParams struct {
	API    SweepAPI
	Logger *observability.CoreLogger

	SweepNodeID string
	MetricKeys  []string
	BatchSize   int
	RunCap      int

	PollInterval time.Duration

	// Clock is real time in production; tests substitute a fake so
	// poll waits do not depend on the wall clock.
	Clock Clock
}

// Scheduler drives one sweep; it implements TaskResolver.
//
// Step and Stop are unimplemented placeholders: the polling and
// optimizer loop that gives them a real body lands on top of this
// contract in a later change.
type Scheduler struct {
	params SchedulerParams
}

var _ TaskResolver = (*Scheduler)(nil)

// NewScheduler constructs a Scheduler from params.
func NewScheduler(params SchedulerParams) *Scheduler {
	return &Scheduler{params: params}
}

// unimplementedDoneTask is what Step returns until it has a real body.
func unimplementedDoneTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
			Done: &spb.SweepSchedulerServerDoneTask{
				Reason:  spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				Message: "scheduler: Step is not implemented",
			},
		},
	}
}

// Step is unimplemented; it always returns a Done task.
func (s *Scheduler) Step(
	context.Context,
	*spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	return unimplementedDoneTask()
}

// Stop is unimplemented; Step never blocks long enough to need one.
func (s *Scheduler) Stop() {}
