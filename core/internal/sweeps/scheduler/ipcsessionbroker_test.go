package scheduler_test

import (
	"context"
	"sync"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// scriptedTaskResolver returns empty generation tasks until stopped, then a
// Done task, like the real scheduler loop.
type scriptedTaskResolver struct {
	mu      sync.Mutex
	stopped bool
}

func (s *scriptedTaskResolver) Step(
	ctx context.Context,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	s.mu.Lock()
	stopped := s.stopped
	s.mu.Unlock()

	if stopped {
		return &spb.SweepSchedulerServerNextTaskResponse{
			Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
				Done: &spb.SweepSchedulerServerDoneTask{
					Reason: spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
				},
			},
		}
	}
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Generation{
			Generation: &spb.SweepSchedulerServerGenerationTask{},
		},
	}
}

func (s *scriptedTaskResolver) Stop() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stopped = true
}

// testFactory records the session contexts and resolvers it created.
type testFactory struct {
	schedCtxs []context.Context
	resolvers []*scriptedTaskResolver
	err       error
}

func (f *testFactory) make(
	schedCtx context.Context,
	reqCtx context.Context,
	req *spb.SweepSchedulerClientInitRequest,
) (scheduler.TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
	if f.err != nil {
		return nil, nil, f.err
	}
	resolver := &scriptedTaskResolver{}
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

func TestInitSchedulerAssignsIDs(t *testing.T) {
	factory := &testFactory{}
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
	factory := &testFactory{err: assert.AnError}
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	_, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))

	assert.ErrorIs(t, err, assert.AnError)
}

func TestSecondInitSameSweepIsRejected(t *testing.T) {
	factory := &testFactory{}
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
	factory := &testFactory{}
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
	factory := &testFactory{}
	broker := newTestBroker(t, factory)
	ctx := context.Background()

	first, err := broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)

	// Drive the first session to its terminal task.
	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: first.SessionId})
	response := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: first.SessionId})
	require.NotNil(t, response.GetDone())

	_, err = broker.InitScheduler(ctx, ctx, initRequest("sweep-a"))

	assert.NoError(t, err)
}

func TestInitsForDifferentSweepsCoexist(t *testing.T) {
	factory := &testFactory{}
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
	broker := newTestBroker(t, &testFactory{})

	response := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: "scheduler-99"})

	done := response.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	assert.Contains(t, done.Message, "unknown scheduler id")
}

func TestNextTaskRoutesToSession(t *testing.T) {
	factory := &testFactory{}
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(
		ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)

	response := broker.NextTask(
		&spb.SweepSchedulerClientNextTaskRequest{SessionId: initResponse.SessionId})

	assert.NotNil(t, response.GetGeneration())
	assert.EqualValues(t, 1, response.TaskSeq)
}

func TestStopRoutesToSessionAndIgnoresUnknown(t *testing.T) {
	factory := &testFactory{}
	broker := newTestBroker(t, factory)
	ctx := context.Background()
	initResponse, err := broker.InitScheduler(
		ctx, ctx, initRequest("sweep-a"))
	require.NoError(t, err)

	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: initResponse.SessionId})
	broker.Stop(&spb.SweepSchedulerClientStopRequest{SessionId: "scheduler-99"})

	assert.True(t, factory.resolvers[0].stopped)
}

func TestShutdownCancelsAllSessions(t *testing.T) {
	factory := &testFactory{}
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
