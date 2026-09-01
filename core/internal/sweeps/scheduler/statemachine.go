package scheduler

import (
	"context"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TaskResolver computes one scheduling step for a sweep.
//
// Implemented by the scheduler loop; faked in tests of the state machine.
type TaskResolver interface {
	// Step applies the previous task's result (nil on the first step),
	// then blocks up to about one poll interval and returns the next
	// task. Returning a Done task ends the scheduler.
	//
	// ctx is the scheduler session's context; cancellation must make
	// Step return a Done task promptly.
	Step(
		ctx context.Context,
		result *spb.SweepSchedulerClientTaskResult,
	) *spb.SweepSchedulerServerNextTaskResponse

	// Stop asks Step to return a Done task: abandon an in-flight poll,
	// or enqueue in-flight suggestions once and then exit.
	//
	// Must not block; safe to call at any time, including concurrently
	// with Step.
	Stop()
}

// schedulerStateMachine makes the task exchange idempotent.
//
// Each task is delivered with a sequence number and retained until a
// result echoing that number is accepted, exactly once. A poll carrying
// no result or a stale one gets the retained task redelivered without
// invoking the resolver, so lost responses and client retries cannot skip
// or double-apply work. Once the resolver returns a Done task it is cached
// and answers every later poll.
type schedulerStateMachine struct {
	// mu serializes polls; the scheduler's state needs no other locks
	// because all work happens inside Step under this mutex.
	mu sync.Mutex

	// sessionCtx spans the scheduler's lifetime, not one request's:
	// applying a result must not be interrupted just because the client
	// stopped waiting for the response.
	sessionCtx context.Context

	resolver TaskResolver

	// logger is bound with the session's id and sweep, so its lines can
	// be filtered per session.
	logger *observability.CoreLogger

	taskSeq     uint64
	outstanding *spb.SweepSchedulerServerNextTaskResponse
	terminal    *spb.SweepSchedulerServerNextTaskResponse
}

func newSchedulerStateMachine(
	sessionCtx context.Context,
	resolver TaskResolver,
	logger *observability.CoreLogger,
) *schedulerStateMachine {
	return &schedulerStateMachine{
		sessionCtx: sessionCtx,
		resolver:   resolver,
		logger:     logger,
	}
}

// NextTask reports the previous task's result and returns the next task.
//
// Blocks up to about one poll interval. Safe to call concurrently; calls
// are serialized, and a concurrent duplicate poll receives the retained
// unacknowledged task.
func (m *schedulerStateMachine) NextTask(
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.terminal != nil {
		m.logger.Debug(
			"scheduler: redelivering terminal task",
			"seq", m.terminal.TaskSeq)
		return m.terminal
	}

	if m.outstanding != nil {
		if result == nil || result.TaskSeq != m.outstanding.TaskSeq {
			// The client never processed the outstanding task (a lost
			// response or a retried poll); deliver it again unchanged.
			m.logger.Debug(
				"scheduler: redelivering unacknowledged task",
				"seq", m.outstanding.TaskSeq)
			return m.outstanding
		}
		m.outstanding = nil
		m.logger.Debug(
			"scheduler: applying task result",
			"seq", result.TaskSeq)
		return m.step(result)
	}

	// Nothing outstanding, so this is the first poll; there is no task a
	// result could answer, so any result leg is ignored.
	return m.step(nil)
}

// Stop asks the resolver to finish the current step and stop.
func (m *schedulerStateMachine) Stop() {
	// Deliberately does not take mu: a Step may be blocked under it.
	m.resolver.Stop()
}

// step runs the resolver once and records the task it returns.
func (m *schedulerStateMachine) step(
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	task := m.resolver.Step(m.sessionCtx, result)
	if task == nil {
		// A resolver must always produce a task; treat a missing one as
		// a shutdown so the client is never left without a reply.
		m.logger.Error("scheduler: resolver returned no task")
		task = &spb.SweepSchedulerServerNextTaskResponse{
			Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
				Done: &spb.SweepSchedulerServerDoneTask{
					Reason: spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
				},
			},
		}
	}

	m.taskSeq++
	task.TaskSeq = m.taskSeq

	m.logger.Debug(
		"scheduler: task issued",
		"seq", m.taskSeq,
		"task", taskType(task))

	if task.GetDone() != nil {
		m.terminal = task
	} else {
		m.outstanding = task
	}
	return task
}

// taskType names a task for logs.
func taskType(task *spb.SweepSchedulerServerNextTaskResponse) string {
	switch {
	case task.GetWarmStart() != nil:
		return "warm_start"
	case task.GetGeneration() != nil:
		return "generation"
	case task.GetDone() != nil:
		return "done"
	default:
		return "unknown"
	}
}
