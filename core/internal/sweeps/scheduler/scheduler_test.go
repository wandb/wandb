package scheduler_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// testRun scripts one poll row.
type testRun struct {
	name    string
	state   string
	config  string // wire form; "" means {}
	summary string
	history string
}

// pollJSON builds a SweepRunsWithHistory response.
func pollJSON(sweepState string, hasNext bool, cursor string, runs ...testRun) string {
	edges := make([]map[string]any, 0, len(runs))
	for _, run := range runs {
		config := run.config
		if config == "" {
			config = "{}"
		}
		summary := run.summary
		if summary == "" {
			summary = "{}"
		}
		var history []any
		if run.history != "" {
			var rows any
			if err := json.Unmarshal([]byte(run.history), &rows); err != nil {
				panic(err)
			}
			history = []any{rows}
		}
		edges = append(edges, map[string]any{
			"node": map[string]any{
				"id":             fmt.Sprintf("node-%s", run.name),
				"name":           run.name,
				"state":          orNil(run.state),
				"config":         config,
				"summaryMetrics": summary,
				"sampledHistory": history,
			},
		})
	}

	response := map[string]any{
		"project": map[string]any{
			"sweep": map[string]any{
				"state": sweepState,
				"runs": map[string]any{
					"pageInfo": map[string]any{
						"hasNextPage": hasNext,
						"endCursor":   orNil(cursor),
					},
					"edges": edges,
				},
			},
		},
	}
	encoded, err := json.Marshal(response)
	if err != nil {
		panic(err)
	}
	return string(encoded)
}

func orNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// fakeClock lets tests control the scheduler's notion of now and fires
// every timer immediately so failure slowdowns cost no test time.
type fakeClock struct {
	now time.Time
}

func (c *fakeClock) Now() time.Time { return c.now }

func (c *fakeClock) NewTimer(time.Duration) (<-chan time.Time, func()) {
	fire := make(chan time.Time, 1)
	fire <- time.Time{}
	return fire, func() {}
}

// loopFixture wires a Scheduler to a mock backend.
type loopFixture struct {
	client    *gqlmock.MockClient
	scheduler *scheduler.Scheduler
	clock     *fakeClock
}

func newLoopFixture(t *testing.T, params scheduler.SchedulerParams) *loopFixture {
	t.Helper()

	fixture := &loopFixture{
		client: gqlmock.NewMockClient(),
		clock:  &fakeClock{now: time.Date(2026, 8, 21, 12, 0, 0, 0, time.UTC)},
	}

	params.API = scheduler.NewSweepAPI(
		fixture.client,
		featurechecker.NewPreloaded(map[spb.ServerFeature]bool{
			spb.ServerFeature_SWEEPS_LOCAL_SCHEDULER: true,
		}),
		"test-entity", "test-project", "test-sweep",
	)
	params.Logger = observability.NewNoOpLogger()
	params.SweepNodeID = "sweep-node-id"
	if params.PollInterval == 0 {
		params.PollInterval = time.Millisecond
	}
	if params.Clock == nil {
		params.Clock = fixture.clock
	}

	fixture.scheduler = scheduler.NewScheduler(params)
	return fixture
}

func (f *loopFixture) stubPoll(response string) {
	f.client.StubMatchOnce(gqlmock.WithOpName("SweepRunsWithHistory"), response)
}

// stubSweepConfig answers the sweep re-check an enqueue performs.
func (f *loopFixture) stubSweepConfig(sweepState string) {
	f.client.StubMatchOnce(
		gqlmock.WithOpName("SweepConfig"),
		fmt.Sprintf(`{"project": {"sweep": {"id": "sweep-node-id",
			"state": %q, "config": "", "displayName": ""}}}`, sweepState),
	)
}

// stubEnqueue answers one enqueue by minting a run named runName.
func (f *loopFixture) stubEnqueue(runName string) {
	f.client.StubMatchOnce(
		gqlmock.WithOpName("EnqueueSweepRun"),
		fmt.Sprintf(
			`{"enqueueSweepRun": {"id": %q, "runQueueItemId": "rqi"}}`,
			runName),
	)
}

// stubFinishSweep answers the loop's request to finish the sweep.
func (f *loopFixture) stubFinishSweep() {
	f.client.StubMatchOnce(
		gqlmock.WithOpName("UpsertSweepState"),
		`{"upsertSweep": {"sweep": {"state": "FINISHED"}}}`,
	)
}

// step drives one Step with a timeout guard.
func (f *loopFixture) step(
	t *testing.T,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	t.Helper()

	done := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() { done <- f.scheduler.Step(context.Background(), result) }()
	return schedulertest.Receive(t, done)
}

// warmTo drains warm start with no prior runs, leaving the scheduler
// iterating. The caller stubs subsequent polls.
func (f *loopFixture) warmTo(t *testing.T) {
	t.Helper()
	f.stubPoll(pollJSON("RUNNING", false, ""))
	task := f.step(t, nil)
	require.NotNil(t, task.GetWarmStart(), "expected a warm-start task")
	require.False(t, task.GetWarmStart().HasMore)
}

func warmResult(adoptions map[string]string) *spb.SweepSchedulerClientTaskResult {
	return &spb.SweepSchedulerClientTaskResult{
		Result: &spb.SweepSchedulerClientTaskResult_WarmStart{
			WarmStart: &spb.SweepSchedulerClientWarmStartResult{
				Adoptions: adoptions,
			},
		},
	}
}

func generationResult(
	generation *spb.SweepSchedulerClientGenerationResult,
) *spb.SweepSchedulerClientTaskResult {
	return &spb.SweepSchedulerClientTaskResult{
		Result: &spb.SweepSchedulerClientTaskResult_Generation{
			Generation: generation,
		},
	}
}

func suggest(ids ...string) *spb.SweepSchedulerClientGenerationResult {
	result := &spb.SweepSchedulerClientGenerationResult{
		AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_SUGGESTED,
	}
	for _, id := range ids {
		result.Suggestions = append(result.Suggestions,
			&spb.SweepSchedulerClientRunSuggestion{
				OptimizerRunId: id,
				ConfigJson:     `{"param1": 1}`,
			})
	}
	return result
}

func emptyIterResult() *spb.SweepSchedulerClientTaskResult {
	return generationResult(&spb.SweepSchedulerClientGenerationResult{})
}

func TestDeclinedAskAsksAgain(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	first := fixture.step(t, warmResult(nil))
	require.EqualValues(t, 1, first.GetGeneration().AskUpTo)

	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	second := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_DECLINED,
		}))

	// No enqueue happened (no stub for it) and the ask repeats.
	require.NotNil(t, second.GetGeneration())
	assert.EqualValues(t, 1, second.GetGeneration().AskUpTo)
}

func TestTerminateFinishesSweep(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	fixture.stubFinishSweep()
	done := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{Terminate: true}))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_TERMINATED,
		done.GetDone().Reason)
}

func TestOptimizerErrorEndsLoopWithoutFinishingSweep(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	// No UpsertSweepState stub: finishing the sweep here would fail the
	// test via an unstubbed call.
	done := fixture.step(t, &spb.SweepSchedulerClientTaskResult{
		Result: &spb.SweepSchedulerClientTaskResult_Error{
			Error: &spb.SweepSchedulerClientTaskError{
				Message: "the optimizer exploded",
			},
		},
	})

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_OPTIMIZER_ERROR,
		done.GetDone().Reason)
	assert.Contains(t, done.GetDone().Message, "exploded")
}

func TestStopDuringPollExitsWithoutAsking(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	fixture.client.StubMatchHang(gqlmock.WithOpName("SweepRunsWithHistory"))

	pollsBefore := 0
	for _, req := range fixture.client.AllRequests() {
		if req.OpName == "SweepRunsWithHistory" {
			pollsBefore++
		}
	}

	done := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		done <- fixture.scheduler.Step(context.Background(), emptyIterResult())
	}()

	require.Eventually(t, func() bool {
		n := 0
		for _, req := range fixture.client.AllRequests() {
			if req.OpName == "SweepRunsWithHistory" {
				n++
			}
		}
		return n > pollsBefore
	}, 2*time.Second, 10*time.Millisecond)

	fixture.scheduler.Stop()

	task := schedulertest.Receive(t, done)
	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
}

func TestSessionCancelReturnsShutdown(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	task := fixture.scheduler.Step(ctx, nil)

	// The warm-start page may complete, but the following generation's
	// sleep observes the cancelled context.
	if task.GetWarmStart() != nil {
		task = fixture.scheduler.Step(ctx, warmResult(nil))
	}
	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
}

func TestTellErrorPopsRunAndContinues(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "poison", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"poison": "opt-p"}))

	// The optimizer failed to ingest the run; it stops being tracked
	// and frees its slot.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "poison", state: "running"},
	))
	task := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			TellErrors: []*spb.SweepSchedulerClientTellError{
				{OptimizerRunId: "opt-p", Message: "bad summary"},
			},
		}))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Empty(t, generation.Updates)
	assert.EqualValues(t, 2, generation.AskUpTo)
}

func TestDuplicateAdoptionReportedAsDiscarded(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 3})
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
		testRun{name: "run-2", state: "running"},
	))
	fixture.step(t, nil)

	// Both runs claim the same optimizer id; the second is dropped, and
	// the optimizer is told so rather than waiting for updates forever.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
		testRun{name: "run-2", state: "running"},
	))
	task := fixture.step(t, warmResult(map[string]string{
		"run-1": "opt-dup",
		"run-2": "opt-dup",
	}))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Equal(t, []string{"opt-dup"}, generation.DiscardedOptimizerRunIds)
	// Exactly one of the two runs is tracked.
	assert.Len(t, generation.Updates, 1)
}
