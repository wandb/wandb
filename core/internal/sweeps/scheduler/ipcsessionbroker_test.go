package scheduler_test

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// testFactory hands the broker mock resolvers and records the session
// contexts it created them with.
type testFactory struct {
	ctrl      *gomock.Controller
	schedCtxs []context.Context
	resolvers []*schedulertest.MockTaskResolver
	err       error
}

func newTestFactory(t *testing.T) *testFactory {
	return &testFactory{ctrl: gomock.NewController(t)}
}

func (f *testFactory) make(
	schedCtx context.Context,
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
) (scheduler.TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
	if f.err != nil {
		return nil, nil, f.err
	}
	resolver := schedulertest.NewMockTaskResolver(f.ctrl)
	f.schedCtxs = append(f.schedCtxs, schedCtx)
	f.resolvers = append(f.resolvers, resolver)
	return resolver, &spb.SweepSchedulerServerInitResponse{
		SweepConfig: "method: grid",
	}, nil
}

func initRequest(sweepID string) *spb.SweepSchedulerClientInitRequest {
	return &spb.SweepSchedulerClientInitRequest{
		Entity:  "test-entity",
		Project: "test-project",
		SweepId: sweepID,
	}
}

// newTestBroker builds a broker logging to the test's output.
//
// It is shut down when the test ends, so no session watcher outlives
// the test that created it.
func newTestBroker(t *testing.T, factory *testFactory) *scheduler.IPCSessionBroker {
	broker := scheduler.NewIPCSessionBroker(
		factory.make, observabilitytest.NewTestLogger(t))
	t.Cleanup(broker.Shutdown)
	return broker
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
	// The rejected init leaves the live session untouched, and its
	// factory never ran.
	assert.NoError(t, factory.schedCtxs[0].Err())
	assert.Len(t, factory.schedCtxs, 1)
}

func TestRerunAllowedAfterClientDies(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	connCtx, cancel := context.WithCancel(context.Background())
	reqCtx := context.Background()

	_, err1 := broker.InitScheduler(connCtx, reqCtx, initRequest("sweep-a"))
	require.NoError(t, err1)
	cancel() // The first client's connection dies mid-sweep.

	_, err2 := broker.InitScheduler(
		context.Background(), reqCtx, initRequest("sweep-a"))

	assert.NoError(t, err2)
}

func TestRerunAllowedAfterSchedulerFinishes(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	first, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	factory.resolvers[0].EXPECT().Stop()
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(shutdownTask())

	// Drive the first session to its terminal task.
	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: first.SessionId})
	response := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: first.SessionId})
	require.NotNil(t, response.GetDone())

	_, err = broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))

	assert.NoError(t, err)
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

	first := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})
	second := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})

	require.NotNil(t, first.GetDone())
	// The scheduler's context ends with it, so the run state and API
	// client it held are no longer pinned.
	assert.Error(t, factory.schedCtxs[0].Err())
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
	// The outstanding Step ends with the session's context, as a
	// resolver must.
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

	polled := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		polled <- broker.NextTask(
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
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})
	require.NotNil(t, response.GetDone())
	assert.Contains(t, response.GetDone().Message, "unknown scheduler id")
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
	// resolver ends with its context instead.
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Any()).
		Return(generationTask()).
		AnyTimes()

	cancel() // The client's connection dies between polls.

	// No poll is in flight to notice, so the session's own context is
	// what drops it, from a goroutine of its own.
	done := pollUntilDropped(t, broker, initResponse.SessionId)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	assert.Contains(t, done.Message, "unknown scheduler id")
}

func TestInitsForDifferentSweepsCoexist(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	_, err1 := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	_, err2 := broker.InitScheduler(ctx, ctx, initRequest("sweep-b"))

	require.NoError(t, err1)
	require.NoError(t, err2)
	assert.NoError(t, factory.schedCtxs[0].Err())
	assert.NoError(t, factory.schedCtxs[1].Err())
}

func TestNextTaskUnknownIDReturnsFatalDone(t *testing.T) {
	broker := newTestBroker(t, newTestFactory(t))

	response := broker.NextTask(
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

func TestShutdownCancelsAllSessions(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	_, err1 := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	_, err2 := broker.InitScheduler(ctx, ctx, initRequest("sweep-b"))
	require.NoError(t, err1)
	require.NoError(t, err2)

	broker.Shutdown()

	assert.Error(t, factory.schedCtxs[0].Err())
	assert.Error(t, factory.schedCtxs[1].Err())
}
