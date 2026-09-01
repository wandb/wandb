package scheduler_test

import (
	"context"
	"testing"

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
func newTestBroker(t *testing.T, factory *testFactory) *scheduler.IPCSessionBroker {
	return scheduler.NewIPCSessionBroker(
		factory.make, observabilitytest.NewTestLogger(t))
}

func generationTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Generation{
			Generation: &spb.SweepSchedulerServerGenerationTask{},
		},
	}
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

func TestNextTaskRoutesToSession(t *testing.T) {
	factory := newTestFactory(t)
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(
		ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)
	factory.resolvers[0].EXPECT().
		Step(gomock.Any(), gomock.Nil()).
		Return(generationTask())

	response := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})

	assert.NotNil(t, response.GetGeneration())
	assert.EqualValues(t, 1, response.TaskSeq)
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
