package scheduler

import (
	"context"
	"sync"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// newTestStateMachine builds a state machine logging to the test's output.
func newTestStateMachine(t *testing.T, resolver TaskResolver) *schedulerStateMachine {
	return newSchedulerStateMachine(
		context.Background(), resolver, observabilitytest.NewTestLogger(t))
}

// fakeTaskResolver scripts Step returns and records the results it received.
type fakeTaskResolver struct {
	mu      sync.Mutex
	tasks   []*spb.SweepSchedulerServerNextTaskResponse
	results []*spb.SweepSchedulerClientTaskResult
	stopped bool

	// blockStep, when non-nil, is received from at the start of each
	// Step call so a test can hold a Step open.
	blockStep chan struct{}
}

func (s *fakeTaskResolver) Step(
	ctx context.Context,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	if s.blockStep != nil {
		<-s.blockStep
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	s.results = append(s.results, result)
	if len(s.tasks) == 0 {
		return nil
	}
	task := s.tasks[0]
	s.tasks = s.tasks[1:]
	return task
}

func (s *fakeTaskResolver) Stop() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stopped = true
}

func (s *fakeTaskResolver) stepCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.results)
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

func TestFirstPollStepsWithNilResult(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks: []*spb.SweepSchedulerServerNextTaskResponse{generationTask()},
	}
	machine := newTestStateMachine(t, resolver)

	task := machine.NextTask(nil)

	assert.EqualValues(t, 1, task.TaskSeq)
	require.Equal(t, 1, resolver.stepCount())
	assert.Nil(t, resolver.results[0])
}

func TestMatchingResultAdvances(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks: []*spb.SweepSchedulerServerNextTaskResponse{
			generationTask(), generationTask(),
		},
	}
	machine := newTestStateMachine(t, resolver)
	first := machine.NextTask(nil)

	second := machine.NextTask(resultForSeq(first.TaskSeq))

	assert.EqualValues(t, 2, second.TaskSeq)
	require.Equal(t, 2, resolver.stepCount())
	assert.EqualValues(t, 1, resolver.results[1].TaskSeq)
}

func TestNilOrStaleResultRedeliversCachedTask(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks: []*spb.SweepSchedulerServerNextTaskResponse{generationTask()},
	}
	machine := newTestStateMachine(t, resolver)
	first := machine.NextTask(nil)

	redeliveredNil := machine.NextTask(nil)
	redeliveredStale := machine.NextTask(resultForSeq(first.TaskSeq + 7))

	assert.Same(t, first, redeliveredNil)
	assert.Same(t, first, redeliveredStale)
	// The resolver never saw the nil or stale results.
	assert.Equal(t, 1, resolver.stepCount())
}

func TestResultAppliedAtMostOnce(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks: []*spb.SweepSchedulerServerNextTaskResponse{
			generationTask(), generationTask(),
		},
	}
	machine := newTestStateMachine(t, resolver)
	first := machine.NextTask(nil)

	second := machine.NextTask(resultForSeq(first.TaskSeq))
	// A retry of the already-consumed result must not re-apply it; it is
	// stale relative to the new outstanding task.
	retried := machine.NextTask(resultForSeq(first.TaskSeq))

	assert.Same(t, second, retried)
	assert.Equal(t, 2, resolver.stepCount())
}

func TestDoneTaskIsTerminalAndCached(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks: []*spb.SweepSchedulerServerNextTaskResponse{doneTask()},
	}
	machine := newTestStateMachine(t, resolver)

	done := machine.NextTask(nil)
	late := machine.NextTask(resultForSeq(done.TaskSeq))
	nilPoll := machine.NextTask(nil)

	require.NotNil(t, done.GetDone())
	assert.Same(t, done, late)
	assert.Same(t, done, nilPoll)
	assert.Equal(t, 1, resolver.stepCount())
}

func TestNilTaskResolverTaskBecomesShutdownDone(t *testing.T) {
	machine := newTestStateMachine(t, &fakeTaskResolver{})

	task := machine.NextTask(nil)

	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
}

func TestConcurrentPollsSerializeAndRedeliver(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks: []*spb.SweepSchedulerServerNextTaskResponse{generationTask()},
		// Hold the first Step open until both polls are in flight.
		blockStep: make(chan struct{}),
	}
	machine := newTestStateMachine(t, resolver)

	responses := make(chan *spb.SweepSchedulerServerNextTaskResponse, 2)
	var wg sync.WaitGroup
	for range 2 {
		wg.Go(func() { responses <- machine.NextTask(nil) })
	}
	resolver.blockStep <- struct{}{}
	wg.Wait()
	close(responses)

	// One poll computed the task and the other was redelivered it; the
	// resolver ran exactly once either way.
	for response := range responses {
		assert.EqualValues(t, 1, response.TaskSeq)
	}
	assert.Equal(t, 1, resolver.stepCount())
}

func TestStopForwardsWhileStepBlocked(t *testing.T) {
	resolver := &fakeTaskResolver{
		tasks:     []*spb.SweepSchedulerServerNextTaskResponse{generationTask()},
		blockStep: make(chan struct{}),
	}
	machine := newTestStateMachine(t, resolver)

	var wg sync.WaitGroup
	wg.Go(func() { machine.NextTask(nil) })

	// Stop must not block on the machine's mutex even though a Step is
	// in progress under it.
	machine.Stop()

	resolver.blockStep <- struct{}{}
	wg.Wait()
	assert.True(t, resolver.stopped)
}
