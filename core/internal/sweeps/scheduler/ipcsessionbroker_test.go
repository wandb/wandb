package scheduler_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// testFactory hands the broker mock resolvers.
type testFactory struct {
	ctrl      *gomock.Controller
	resolvers []*schedulertest.MockTaskResolver
	err       error
}

func newTestFactory(t *testing.T) *testFactory {
	return &testFactory{ctrl: gomock.NewController(t)}
}

func (f *testFactory) make(
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
	sweepAPI scheduler.SweepAPI,
) (scheduler.TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
	if f.err != nil {
		return nil, nil, f.err
	}
	resolver := schedulertest.NewMockTaskResolver(f.ctrl)
	f.resolvers = append(f.resolvers, resolver)
	return resolver, &spb.SweepSchedulerServerInitResponse{
		SweepConfig: "method: grid",
	}, nil
}

func initRequest(sweepID string) *spb.SweepSchedulerClientInitRequest {
	return &spb.SweepSchedulerClientInitRequest{
		Entity:   "test-entity",
		Project:  "test-project",
		SweepId:  sweepID,
		Settings: &spb.Settings{},
	}
}

// newTestBroker builds a broker logging to the test's output.
func newTestBroker(t *testing.T, factory *testFactory) *scheduler.IPCSessionBroker {
	return scheduler.NewIPCSessionBroker(
		factory.make, observabilitytest.NewTestLogger(t))
}

// expectStopped expects Stop at least once and closes the channel on the first.
func expectStopped(resolver *schedulertest.MockTaskResolver) <-chan struct{} {
	stopped := make(chan struct{})
	var once sync.Once
	resolver.EXPECT().Stop().MinTimes(1).Do(func() {
		once.Do(func() { close(stopped) })
	})
	return stopped
}

func shutdownTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
			Done: &spb.SweepSchedulerServerDoneTask{
				Reason: spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
			},
		},
	}
}

func generationTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Generation{
			Generation: &spb.SweepSchedulerServerGenerationTask{},
		},
	}
}

// pollUntilDropped polls a session until the broker no longer knows its
// id, keeping each poll in sync with the task the last one returned,
// and returns the Done that ends it.
//
// A session the broker still tracks answers with a task, which is how
// this tells "not dropped yet" from "dropped". It fails the test if the
// session is still tracked after schedulertest.ReceiveTimeout.
func pollUntilDropped(
	t *testing.T,
	broker *scheduler.IPCSessionBroker,
	sessionID string,
) *spb.SweepSchedulerServerDoneTask {
	t.Helper()

	var result *spb.SweepSchedulerClientTaskResult
	deadline := time.Now().Add(schedulertest.ReceiveTimeout)
	for time.Now().Before(deadline) {
		response := broker.NextTask(
			context.Background(),
			&spb.SweepSchedulerClientNextTaskRequest{
				SessionId: sessionID,
				Result:    result,
			})
		if done := response.GetDone(); done != nil {
			return done
		}
		result = &spb.SweepSchedulerClientTaskResult{TaskSeq: response.TaskSeq}
		time.Sleep(time.Millisecond)
	}

	t.Fatalf(
		"the session was still tracked after %s",
		schedulertest.ReceiveTimeout)
	return nil
}

func TestInitSchedulerAssignsIDs(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	first, err1 := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	second, err2 := broker.InitScheduler(ctx, ctx, initRequest("sweep-b"))

	require.NoError(t, err1)
	require.NoError(t, err2)
	assert.Equal(t, "scheduler-0", first.SessionId)
	assert.Equal(t, "scheduler-1", second.SessionId)
	assert.Equal(t, "method: grid", first.SweepConfig)
}

func TestInitSchedulerFactoryError(t *testing.T) {
	factory := newTestFactory(t)
	factory.err = assert.AnError
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	_, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))

	assert.ErrorIs(t, err, assert.AnError)
}

func TestSecondInitSameSweepIsRejected(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	_, err1 := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	_, err2 := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))

	require.NoError(t, err1)
	assert.ErrorIs(t, err2, scheduler.ErrAlreadyScheduled)
	// The rejected init's factory never ran, and the mock's lack of a
	// Stop expectation asserts the live session was left untouched.
	assert.Len(t, factory.resolvers, 1)
}

func TestRerunAllowedAfterClientDies(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	connCtx, cancel := context.WithCancel(context.Background())
	reqCtx := context.Background()

	_, err1 := broker.InitScheduler(connCtx, reqCtx, initRequest("sweep-a"))
	require.NoError(t, err1)
	stopped := expectStopped(factory.resolvers[0])
	cancel() // The first client's connection dies mid-sweep.

	_, err2 := broker.InitScheduler(
		context.Background(), reqCtx, initRequest("sweep-a"))

	assert.NoError(t, err2)
	schedulertest.Receive(t, stopped)
}

func TestRerunAllowedAfterSchedulerFinishes(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	first, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	stopped := expectStopped(factory.resolvers[0])
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(shutdownTask())

	// Drive the first session to its terminal task.
	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: first.SessionId})
	response := broker.NextTask(
		context.Background(),
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: first.SessionId})
	require.NotNil(t, response.GetDone())

	_, err = broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))

	assert.NoError(t, err)
	schedulertest.Receive(t, stopped)
}

func TestFinishedSessionIsRetired(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	// Exactly one Step runs: the retired session is gone by the second
	// poll, so nothing reaches its resolver again.
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(shutdownTask())
	stopped := expectStopped(factory.resolvers[0])

	first := broker.NextTask(
		context.Background(),
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})
	second := broker.NextTask(
		context.Background(),
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})

	require.NotNil(t, first.GetDone())
	// Ending the session's context stops its resolver too.
	schedulertest.Receive(t, stopped)
	require.NotNil(t, second.GetDone())
	assert.Contains(t, second.GetDone().Message, "unknown scheduler id")
}

func TestSessionEndsWhenClientDiesMidPoll(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	connCtx, cancel := context.WithCancel(context.Background())
	initResponse, err := broker.InitScheduler(
		connCtx, context.Background(), initRequest("sweep-a"))
	require.NoError(t, err)
	// The poll's own context outlives the connection here, so only the
	// Stop the session's end sends can release the outstanding Step.
	stopped := expectStopped(factory.resolvers[0])
	stepping := make(chan struct{})
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		DoAndReturn(func(
			context.Context,
			*spb.SweepSchedulerClientTaskResult,
		) *spb.SweepSchedulerServerNextTaskResponse {
			close(stepping)
			<-stopped
			return shutdownTask()
		})

	polled := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		polled <- broker.NextTask(
			context.Background(),
			&spb.SweepSchedulerClientNextTaskRequest{
				SessionId: initResponse.SessionId,
			})
	}()
	// Kill the connection only once the poll is genuinely in flight.
	schedulertest.Receive(t, stepping)
	cancel()

	require.NotNil(t, schedulertest.Receive(t, polled).GetDone())
	// The session is retired, not left in the broker awaiting a client
	// that is gone.
	response := broker.NextTask(
		context.Background(),
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})
	require.NotNil(t, response.GetDone())
	assert.Contains(t, response.GetDone().Message, "unknown scheduler id")
}

func TestCancelledPollLeavesSessionRunning(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	// The lone expectation also asserts that the abandoned poll never
	// reaches the resolver.
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(generationTask())
	cancelled, cancelPoll := context.WithCancel(context.Background())
	cancelPoll()

	abandoned := broker.NextTask(
		cancelled,
		&spb.SweepSchedulerClientNextTaskRequest{
			SessionId: initResponse.SessionId,
		})

	// Nothing to answer, and the sweep keeps its scheduler: one poll
	// giving up is not the client giving up.
	assert.Nil(t, abandoned)
	resumed := broker.NextTask(
		context.Background(),
		&spb.SweepSchedulerClientNextTaskRequest{
			SessionId: initResponse.SessionId,
		})
	require.NotNil(t, resumed)
	assert.Nil(t, resumed.GetDone())
}

func TestSessionDroppedWhenClientDiesBetweenPolls(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	connCtx, cancel := context.WithCancel(context.Background())
	initResponse, err := broker.InitScheduler(
		connCtx, context.Background(), initRequest("sweep-a"))
	require.NoError(t, err)
	// This resolver keeps answering with tasks, so the only Done the
	// polls below can see is the one for a dropped session. A real
	// resolver ends on Stop instead.
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Any()).
		Return(generationTask()).
		AnyTimes()
	stopped := expectStopped(factory.resolvers[0])

	cancel() // The client's connection dies between polls.

	// No poll is in flight to notice, so the session's own context is
	// what stops and drops it, from a goroutine of its own.
	done := pollUntilDropped(t, broker, initResponse.SessionId)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	assert.Contains(t, done.Message, "unknown scheduler id")
	schedulertest.Receive(t, stopped)
}

func TestInitsForDifferentSweepsCoexist(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	_, err1 := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	_, err2 := broker.InitScheduler(ctx, ctx, initRequest("sweep-b"))

	require.NoError(t, err1)
	require.NoError(t, err2)
	// Both sessions are still live: neither sweep can be scheduled again.
	_, errA := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	_, errB := broker.InitScheduler(ctx, ctx, initRequest("sweep-b"))
	assert.ErrorIs(t, errA, scheduler.ErrAlreadyScheduled)
	assert.ErrorIs(t, errB, scheduler.ErrAlreadyScheduled)
}

func TestNextTaskUnknownIDReturnsFatalDone(t *testing.T) {
	broker := newTestBroker(t, newTestFactory(t))

	response := broker.NextTask(
		context.Background(),
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: "scheduler-99"})

	done := response.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	assert.Contains(t, done.Message, "unknown scheduler id")
}

func TestStopRoutesToSessionAndIgnoresUnknown(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(
		ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	// Exactly one Stop must reach the session; the unknown id is dropped.
	factory.resolvers[0].EXPECT().Stop()

	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: initResponse.SessionId})
	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: "scheduler-99"})
}

func TestCancelledPollEndsItsStep(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	stopped := expectStopped(factory.resolvers[0])
	stepping := make(chan struct{})
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		DoAndReturn(func(
			ctx context.Context,
			_ *spb.SweepSchedulerClientTaskResult,
		) *spb.SweepSchedulerServerNextTaskResponse {
			close(stepping)
			<-ctx.Done()
			return shutdownTask()
		})
	pollCtx, cancelPoll := context.WithCancel(ctx)

	polled := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		polled <- broker.NextTask(
			pollCtx,
			&spb.SweepSchedulerClientNextTaskRequest{
				SessionId: initResponse.SessionId,
			})
	}()
	schedulertest.Receive(t, stepping)
	cancelPoll()

	// The Step runs under the poll's context, so abandoning the poll ends it.
	require.NotNil(t, schedulertest.Receive(t, polled).GetDone())
	schedulertest.Receive(t, stopped)
}

func TestStoppedSessionAbandonsPendingSuggestions(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	broker := scheduler.NewIPCSessionBroker(
		func(
			context.Context,
			*spb.SweepSchedulerClientInitRequest,
			scheduler.SweepAPI,
		) (scheduler.TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
			return fixture.scheduler, &spb.SweepSchedulerServerInitResponse{}, nil
		},
		observabilitytest.NewTestLogger(t))
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	poll := func(
		result *spb.SweepSchedulerClientTaskResult,
	) *spb.SweepSchedulerServerNextTaskResponse {
		polled := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
		go func() {
			polled <- broker.NextTask(ctx, &spb.SweepSchedulerClientNextTaskRequest{
				SessionId: initResponse.SessionId,
				Result:    result,
			})
		}()
		return schedulertest.Receive(t, polled)
	}
	fixture.stubWarmStart(warmJSON("RUNNING", false, ""))
	warm := poll(nil)
	fixture.stubIdlePoll("RUNNING")
	warmDone := warmResult(nil)
	warmDone.TaskSeq = warm.TaskSeq
	generation := poll(warmDone)
	require.NotNil(t, generation.GetGeneration())

	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: initResponse.SessionId})
	// Hanging stubs fail on the cancelled context as a real client does.
	fixture.client.StubMatchHang(gqlmock.WithOpName("SweepConfig"))
	fixture.client.StubMatchHang(gqlmock.WithOpName("EnqueueSweepRun"))
	suggested := generationResult(suggest("opt-a", "opt-b"))
	suggested.TaskSeq = generation.TaskSeq
	done := poll(suggested)

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		done.GetDone().Reason)
	assert.Len(t, fixture.requestsFor("EnqueueSweepRun"), 1,
		"the first cancelled enqueue must end the batch")
	assert.Empty(t, fixture.requestsFor("SweepWatchedRuns"),
		"must not poll again after a stop")
	assert.Empty(t, fixture.requestsFor("UpsertSweepState"),
		"a stop must not transition the sweep")
}
