package scheduler

import (
	"context"
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TaskResolver computes one scheduling step for a sweep.
type TaskResolver interface {
	// Step applies the previous task's result (nil on the first step),
	// then blocks up to one poll interval and returns the next task
	Step(
		ctx context.Context,
		result *spb.SweepSchedulerClientTaskResult,
	) *spb.SweepSchedulerServerNextTaskResponse

	// Stop asks Step to return a Done task
	Stop()
}

// schedulerStateMachine sequences the task exchange of one session.
type schedulerStateMachine struct {
	mu sync.Mutex

	// sessionCtx allows the scheduler to detect client disconnect
	sessionCtx context.Context

	resolver TaskResolver

	// logger is bound with the session's id and sweep.
	logger *observability.CoreLogger

	// taskSeq numbers the task last issued, which must be answered
	taskSeq uint64

	terminal *spb.SweepSchedulerServerNextTaskResponse
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
// Safe to call concurrently; calls are serialized under mu.
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

	if err := m.checkAnswersLastTask(result); err != nil {
		m.logger.Error(
			"scheduler: out of sync with the client",
			"error", err)
		return m.finish(&spb.SweepSchedulerServerDoneTask{
			Reason: spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
			Message: fmt.Sprintf(
				"the scheduler and this client are out of sync: %s."+
					" Rerun the scheduler to resume the sweep.", err),
		})
	}

	if result != nil {
		m.logger.Debug(
			"scheduler: applying task result",
			"seq", result.TaskSeq)
	}
	return m.step(result)
}

// checkAnswersLastTask verifies that a poll's result answers the task the
// client was last given.
func (m *schedulerStateMachine) checkAnswersLastTask(
	result *spb.SweepSchedulerClientTaskResult,
) error {
	if m.taskSeq == 0 {
		if result != nil {
			return fmt.Errorf(
				"the first poll reported a result for task %d, but no task"+
					" has been issued yet",
				result.TaskSeq)
		}
		return nil
	}

	switch {
	case result == nil:
		return fmt.Errorf(
			"a poll reported no result, but task %d is awaiting one",
			m.taskSeq)
	case result.TaskSeq != m.taskSeq:
		return fmt.Errorf(
			"a poll reported a result for task %d, but task %d is awaiting"+
				" one",
			result.TaskSeq, m.taskSeq)
	default:
		return nil
	}
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
		// A resolver must always produce a task; treat a missing one
		// as shutdown so the client always gets a reply.
		m.logger.Error("scheduler: resolver returned no task")
		return m.finish(&spb.SweepSchedulerServerDoneTask{
			Reason: spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		})
	}

	m.taskSeq++
	task.TaskSeq = m.taskSeq

	m.logger.Debug(
		"scheduler: task issued",
		"seq", m.taskSeq,
		"task", taskType(task))

	if task.GetDone() != nil {
		m.terminal = task
	}
	return task
}

// finish numbers a Done task and caches it as the session's answer to
// every later poll.
func (m *schedulerStateMachine) finish(
	done *spb.SweepSchedulerServerDoneTask,
) *spb.SweepSchedulerServerNextTaskResponse {
	m.taskSeq++
	m.terminal = &spb.SweepSchedulerServerNextTaskResponse{
		TaskSeq: m.taskSeq,
		Task:    &spb.SweepSchedulerServerNextTaskResponse_Done{Done: done},
	}
	return m.terminal
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
