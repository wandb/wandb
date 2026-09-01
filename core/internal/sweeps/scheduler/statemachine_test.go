package scheduler

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// newTestResolver builds a mock resolver verified when the test ends.
func newTestResolver(t *testing.T) *schedulertest.MockTaskResolver {
	return schedulertest.NewMockTaskResolver(gomock.NewController(t))
}

// newTestStateMachine builds a state machine logging to the test's output.
func newTestStateMachine(t *testing.T, resolver TaskResolver) *schedulerStateMachine {
	return newSchedulerStateMachine(
		context.Background(), resolver, observabilitytest.NewTestLogger(t))
}

func generationTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Generation{
			Generation: &spb.SweepSchedulerServerGenerationTask{},
		},
	}
}

func doneTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
			Done: &spb.SweepSchedulerServerDoneTask{
				Reason: spb.SweepSchedulerServerDoneTask_REASON_EXHAUSTED,
			},
		},
	}
}

func resultForSeq(seq uint64) *spb.SweepSchedulerClientTaskResult {
	return &spb.SweepSchedulerClientTaskResult{TaskSeq: seq}
}

// answering matches the result that answers task seq.
func answering(seq uint64) gomock.Matcher {
	return gomock.Cond(func(result *spb.SweepSchedulerClientTaskResult) bool {
		return result != nil && result.TaskSeq == seq
	})
}

func TestFirstPollStepsWithNilResult(t *testing.T) {
	resolver := newTestResolver(t)
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(generationTask())
	machine := newTestStateMachine(t, resolver)

	task := machine.NextTask(nil)

	assert.EqualValues(t, 1, task.TaskSeq)
}

func TestMatchingResultAdvances(t *testing.T) {
	resolver := newTestResolver(t)
	gomock.InOrder(
		resolver.EXPECT().
			Step(gomock.Any(), gomock.Nil()).
			Return(generationTask()),
		resolver.EXPECT().
			Step(gomock.Any(), answering(1)).
			Return(generationTask()),
	)
	machine := newTestStateMachine(t, resolver)
	first := machine.NextTask(nil)

	second := machine.NextTask(resultForSeq(first.TaskSeq))

	assert.EqualValues(t, 2, second.TaskSeq)
}

func TestMissingResultEndsSessionWithFatalDone(t *testing.T) {
	resolver := newTestResolver(t)
	// The lone expectation also asserts that the resolver never sees the
	// desynchronized poll.
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(generationTask())
	machine := newTestStateMachine(t, resolver)
	machine.NextTask(nil)

	// The client polled again without answering the task it was given.
	response := machine.NextTask(nil)

	done := response.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	assert.Contains(t, done.Message, "out of sync")
}

func TestStaleResultEndsSessionWithFatalDone(t *testing.T) {
	resolver := newTestResolver(t)
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(generationTask())
	machine := newTestStateMachine(t, resolver)
	first := machine.NextTask(nil)

	response := machine.NextTask(resultForSeq(first.TaskSeq + 7))

	done := response.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
}

func TestResultOnFirstPollEndsSessionWithFatalDone(t *testing.T) {
	// No expectations: nothing may reach the resolver.
	resolver := newTestResolver(t)
	machine := newTestStateMachine(t, resolver)

	// No task has been issued, so there is nothing this result can answer.
	response := machine.NextTask(resultForSeq(1))

	done := response.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
}

func TestRepeatedResultEndsSessionWithFatalDone(t *testing.T) {
	resolver := newTestResolver(t)
	gomock.InOrder(
		resolver.EXPECT().
			Step(gomock.Any(), gomock.Nil()).
			Return(generationTask()),
		resolver.EXPECT().
			Step(gomock.Any(), answering(1)).
			Return(generationTask()),
	)
	machine := newTestStateMachine(t, resolver)
	first := machine.NextTask(nil)
	machine.NextTask(resultForSeq(first.TaskSeq))

	// Reporting the same result twice would double-apply it.
	response := machine.NextTask(resultForSeq(first.TaskSeq))

	done := response.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
}

func TestFatalDoneIsCachedForLaterPolls(t *testing.T) {
	resolver := newTestResolver(t)
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(generationTask())
	machine := newTestStateMachine(t, resolver)
	machine.NextTask(nil)
	fatal := machine.NextTask(nil)

	// Once the session has failed, every later poll gets the same answer.
	assert.Same(t, fatal, machine.NextTask(nil))
	assert.Same(t, fatal, machine.NextTask(resultForSeq(fatal.TaskSeq)))
}

func TestDoneTaskIsTerminalAndCached(t *testing.T) {
	resolver := newTestResolver(t)
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(doneTask())
	machine := newTestStateMachine(t, resolver)

	done := machine.NextTask(nil)
	late := machine.NextTask(resultForSeq(done.TaskSeq))
	nilPoll := machine.NextTask(nil)

	require.NotNil(t, done.GetDone())
	assert.Same(t, done, late)
	assert.Same(t, done, nilPoll)
}

func TestNilTaskResolverTaskBecomesShutdownDone(t *testing.T) {
	resolver := newTestResolver(t)
	resolver.EXPECT().Step(gomock.Any(), gomock.Nil()).Return(nil)
	machine := newTestStateMachine(t, resolver)

	task := machine.NextTask(nil)

	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
}

func TestConcurrentPollsSerialize(t *testing.T) {
	resolver := newTestResolver(t)
	stepping := make(chan struct{})
	release := make(chan struct{})
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		DoAndReturn(func(
			context.Context,
			*spb.SweepSchedulerClientTaskResult,
		) *spb.SweepSchedulerServerNextTaskResponse {
			close(stepping)
			<-release
			return generationTask()
		})
	machine := newTestStateMachine(t, resolver)

	responses := make(chan *spb.SweepSchedulerServerNextTaskResponse, 2)
	for range 2 {
		go func() { responses <- machine.NextTask(nil) }()
	}
	// Hold the only Step open until it is under way, so the poll that
	// lost the race meets a Step that is genuinely in flight.
	schedulertest.Receive(t, stepping)
	close(release)

	// The client is supposed to keep one poll outstanding. Both are
	// still answered: one computed the task, and the other could not be
	// answering it, so it ended the session.
	var tasks, fatals int
	for range 2 {
		if done := schedulertest.Receive(t, responses).GetDone(); done != nil {
			assert.Equal(t,
				spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				done.Reason)
			fatals++
		} else {
			tasks++
		}
	}
	assert.Equal(t, 1, tasks)
	assert.Equal(t, 1, fatals)
}

func TestStopForwardsWhileStepBlocked(t *testing.T) {
	resolver := newTestResolver(t)
	stepping := make(chan struct{})
	release := make(chan struct{})
	resolver.EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		DoAndReturn(func(
			context.Context,
			*spb.SweepSchedulerClientTaskResult,
		) *spb.SweepSchedulerServerNextTaskResponse {
			close(stepping)
			<-release
			return generationTask()
		})
	// The expectation is the assertion: Stop must reach the resolver.
	resolver.EXPECT().Stop()
	machine := newTestStateMachine(t, resolver)

	polled := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() { polled <- machine.NextTask(nil) }()
	schedulertest.Receive(t, stepping)

	// Stop must not block on the machine's mutex while a Step holds it.
	machine.Stop()

	close(release)
	schedulertest.Receive(t, polled)
}
