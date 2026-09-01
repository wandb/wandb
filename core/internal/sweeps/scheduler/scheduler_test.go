package scheduler_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
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

// loopFixture wires a Scheduler to a mock backend.
type loopFixture struct {
	client    *gqlmock.MockClient
	scheduler *scheduler.Scheduler
	now       time.Time
}

func newLoopFixture(t *testing.T, params scheduler.SchedulerParams) *loopFixture {
	t.Helper()

	fixture := &loopFixture{
		client: gqlmock.NewMockClient(),
		now:    time.Date(2026, 8, 21, 12, 0, 0, 0, time.UTC),
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
	if params.Now == nil {
		params.Now = func() time.Time { return fixture.now }
	}
	// Fire timers immediately so failure slowdowns cost no test time.
	params.Timer = func(d time.Duration) (<-chan time.Time, func()) {
		fire := make(chan time.Time, 1)
		fire <- time.Time{}
		return fire, func() {}
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
	select {
	case task := <-done:
		return task
	case <-time.After(10 * time.Second):
		t.Fatal("Step did not return")
		return nil
	}
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

func TestSuggestionsEnqueueAndAppear(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)

	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	first := fixture.step(t, warmResult(nil))
	require.NotNil(t, first.GetGeneration())
	assert.EqualValues(t, 2, first.GetGeneration().AskUpTo)

	// The suggestion triggers a sweep re-check and an enqueue.
	fixture.stubSweepConfig("RUNNING")
	fixture.stubEnqueue("backend-name-1")
	// The minted run appears in the next poll under the enqueued id.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "backend-name-1", state: "pending"},
	))
	second := fixture.step(t, generationResult(suggest("opt-1")))

	task := second.GetGeneration()
	require.NotNil(t, task)
	require.Len(t, task.Updates, 1)
	assert.Equal(t, "backend-name-1", task.Updates[0].Run.WandbRunId)
	assert.Equal(t, "opt-1", task.Updates[0].Run.OptimizerRunId)
	// One slot occupied by the joined run.
	assert.EqualValues(t, 1, task.AskUpTo)
	assert.True(t, fixture.client.AllStubsUsed())
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

func TestExhaustedFinishesSweep(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	fixture.stubFinishSweep()
	done := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_EXHAUSTED,
		}))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_EXHAUSTED,
		done.GetDone().Reason)
	assert.True(t, fixture.client.AllStubsUsed())
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

func TestPruneLifecycle(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)

	// Adopt a running run so there is a prune candidate.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "running"},
	))
	first := fixture.step(t, warmResult(map[string]string{"victim": "opt-v"}))
	require.Equal(t, []string{"opt-v"}, first.GetGeneration().PruneCandidates)

	// The prune stops the run by its storage id.
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("StopRun"),
		`{"stopRun": {"success": true}}`,
	)
	// While the stop propagates the run still reports running, but it
	// must not be told or offered again.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "running"},
	))
	second := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{Prune: []string{"opt-v"}}))

	require.NotNil(t, second.GetGeneration())
	assert.Empty(t, second.GetGeneration().Updates)
	assert.Empty(t, second.GetGeneration().PruneCandidates)

	// Once the backend reports it killed, exactly one terminal update
	// arrives, marked pruned.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "killed"},
	))
	third := fixture.step(t, emptyIterResult())
	task := third.GetGeneration()
	require.Len(t, task.Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_KILLED, task.Updates[0].Run.State)
	assert.True(t, task.Updates[0].Pruned)

	// After the ack the run is gone for good.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "killed"},
	))
	fourth := fixture.step(t, emptyIterResult())
	assert.Empty(t, fourth.GetGeneration().Updates)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestPruneIgnoresNonCandidates(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	// No StopRun stub: pruning an id that was never a candidate must
	// not call the backend.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	task := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			Prune: []string{"never-offered"},
		}))

	require.NotNil(t, task.GetGeneration())
}

func TestStopRunFailureIsNotFatal(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"victim": "opt-v"}))

	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("StopRun"),
		&graphql.HTTPError{StatusCode: 409},
	)
	// The run stays tracked and its real terminal state is delivered.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "finished",
			summary: `{"loss": 0.1}`},
	))
	task := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{Prune: []string{"opt-v"}}))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	require.Len(t, generation.Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FINISHED,
		generation.Updates[0].Run.State)
	assert.False(t, generation.Updates[0].Pruned)
}

func TestReapDeletedRequiresConfirmedAbsence(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "ghost", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"ghost": "opt-g"}))

	// First absent poll: no reap, no update.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	first := fixture.step(t, emptyIterResult())
	assert.Empty(t, first.GetGeneration().Updates)

	// Second absent poll, but the run still exists: no reap.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": {"id": "node-ghost", "state": "running"}}}`,
	)
	second := fixture.step(t, emptyIterResult())
	assert.Empty(t, second.GetGeneration().Updates)

	// Absent twice more and confirmed gone: one synthetic FAILED.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	third := fixture.step(t, emptyIterResult())
	assert.Empty(t, third.GetGeneration().Updates)

	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": null}}`,
	)
	fourth := fixture.step(t, emptyIterResult())
	require.Len(t, fourth.GetGeneration().Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
		fourth.GetGeneration().Updates[0].Run.State)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestFinishedWithoutMetricReclassified(t *testing.T) {
	fixture := newLoopFixture(t,
		scheduler.SchedulerParams{MetricKey: "loss"})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "finished", summary: `{"other": 1}`},
	))
	task := fixture.step(t, emptyIterResult())

	updates := task.GetGeneration().Updates
	require.Len(t, updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED, updates[0].Run.State)
}

func TestNoMetricSweepSkipsReclassification(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "finished", summary: `{}`},
	))
	task := fixture.step(t, emptyIterResult())

	updates := task.GetGeneration().Updates
	require.Len(t, updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FINISHED, updates[0].Run.State)
}

func TestNovelStateFailsTheRun(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "hibernating"},
	))
	task := fixture.step(t, emptyIterResult())

	updates := task.GetGeneration().Updates
	require.Len(t, updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED, updates[0].Run.State)
}

func TestUnreadableStateTwiceFails(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// One unreadable poll keeps the previous state.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: ""},
	))
	first := fixture.step(t, emptyIterResult())
	require.Len(t, first.GetGeneration().Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_RUNNING,
		first.GetGeneration().Updates[0].Run.State)

	// A second unreadable poll fails the run.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: ""},
	))
	second := fixture.step(t, emptyIterResult())
	require.Len(t, second.GetGeneration().Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
		second.GetGeneration().Updates[0].Run.State)
}

func TestPausedSweepIdles(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubPoll(pollJSON("PAUSED", false, ""))
	task := fixture.step(t, warmResult(nil))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Empty(t, generation.Updates)
	assert.Zero(t, generation.AskUpTo)
}

func TestExternallyFinishedSweepEndsLoop(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubPoll(pollJSON("FINISHED", false, ""))
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		done.GetDone().Reason)
}

func TestLateSuggestionsDiscardedWhenSweepFinished(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	// The sweep finished while the optimizer was thinking; its
	// suggestions must be discarded, not enqueued.
	fixture.stubSweepConfig("FINISHED")
	done := fixture.step(t, generationResult(suggest("opt-late")))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		done.GetDone().Reason)
	assert.Equal(t,
		[]string{"opt-late"}, done.GetDone().DiscardedOptimizerRunIds)
}

func TestSweepNotFoundEndsLoop(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubPoll(`{"project": {"sweep": null}}`)
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_NOT_FOUND,
		done.GetDone().Reason)
}

func TestFatalPollErrorEndsLoopImmediately(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		&graphql.HTTPError{StatusCode: 403},
	)
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
		done.GetDone().Reason)
}

func TestTransientPollErrorsGiveUpEventually(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	result := emptyIterResult()
	for polls := 0; ; polls++ {
		require.Less(t, polls, 11, "the loop never gave up")

		fixture.client.StubMatchWithError(
			gqlmock.WithOpName("SweepRunsWithHistory"),
			&graphql.HTTPError{StatusCode: 502},
		)
		task := fixture.step(t, result)
		if done := task.GetDone(); done != nil {
			assert.Equal(t,
				spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				done.Reason)
			assert.Contains(t, done.Message, "too many consecutive")
			break
		}
		// Empty tasks while the backend misbehaves.
		assert.Empty(t, task.GetGeneration().Updates)
	}
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

func TestEnqueueFailureEndsTheSchedulerWithTheDiscard(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	fixture.stubSweepConfig("RUNNING")
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("EnqueueSweepRun"),
		&graphql.HTTPError{StatusCode: 502},
	)
	task := fixture.step(t, generationResult(suggest("opt-lost")))

	done := task.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	assert.Contains(t, done.Message, "failed to enqueue")
	// The discard rides the Done task so the optimizer still forgets
	// the suggestion.
	assert.Equal(t,
		[]string{"opt-lost"}, done.DiscardedOptimizerRunIds)
}

func TestDuplicateSuggestionIDDiscarded(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// "opt-1" collides with the adoption; only the backend re-check
	// runs, no enqueue.
	fixture.stubSweepConfig("RUNNING")
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	task := fixture.step(t, generationResult(suggest("opt-1")))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Equal(t,
		[]string{"opt-1"}, generation.DiscardedOptimizerRunIds)
}

func TestEnqueuedRunDeletedBeforeAppearingIsReaped(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	fixture.stubSweepConfig("RUNNING")
	fixture.stubEnqueue("minted-1")

	// The minted run never shows up: it was deleted before appearing.
	// Two missing polls plus a confirming query reap it as failed.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	first := fixture.step(t, generationResult(suggest("opt-1")))
	assert.Empty(t, first.GetGeneration().Updates)

	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": null}}`,
	)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	second := fixture.step(t, emptyIterResult())

	updates := second.GetGeneration().Updates
	require.Len(t, updates, 1)
	assert.Equal(t, "minted-1", updates[0].Run.WandbRunId)
	assert.Equal(t, "opt-1", updates[0].Run.OptimizerRunId)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED, updates[0].Run.State)
}

func TestPendingRunKeepsSlot(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{
		BatchSize: 1,
	})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "stuck", state: "pending"},
	))
	fixture.step(t, warmResult(map[string]string{"stuck": "opt-s"}))

	// However long the run stays pending, it holds its slot and is
	// never stopped (no StopRun stub).
	fixture.now = fixture.now.Add(time.Hour)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "stuck", state: "pending"},
	))
	task := fixture.step(t, emptyIterResult())

	generation := task.GetGeneration()
	require.Len(t, generation.Updates, 1)
	assert.Zero(t, generation.AskUpTo)
}

func TestStopEnqueuesPendingSuggestionsThenDone(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	fixture.scheduler.Stop()

	// Graceful shutdown enqueues the batch the client already produced,
	// then returns Done without another poll or ask.
	fixture.stubSweepConfig("RUNNING")
	fixture.stubEnqueue("minted-a")
	fixture.stubEnqueue("minted-b")
	done := fixture.step(t, generationResult(suggest("opt-a", "opt-b")))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		done.GetDone().Reason)
	assert.Empty(t, done.GetDone().DiscardedOptimizerRunIds)
	assert.True(t, fixture.client.AllStubsUsed(),
		"must not poll again after enqueueing the in-flight suggestions")
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

	select {
	case task := <-done:
		require.NotNil(t, task.GetDone())
		assert.Equal(t,
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
			task.GetDone().Reason)
	case <-time.After(2 * time.Second):
		t.Fatal("Step did not return after Stop during poll")
	}
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

func TestResumedRunIsNotRetoldNorCounted(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// The run finishes; its terminal update is delivered and acked.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "finished", summary: `{"loss": 1}`},
	))
	terminal := fixture.step(t, emptyIterResult())
	require.Len(t, terminal.GetGeneration().Updates, 1)

	// The run resumes: no second terminal tell, and it does not count
	// toward the batch.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	resumed := fixture.step(t, emptyIterResult())

	generation := resumed.GetGeneration()
	assert.Empty(t, generation.Updates)
	assert.EqualValues(t, 2, generation.AskUpTo)
}

func TestEmptySuggestionIDDiscarded(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	// An empty id would join to any run without a display name, so the
	// suggestion is dropped before it is enqueued (no enqueue stub).
	fixture.stubSweepConfig("RUNNING")
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	task := fixture.step(t, generationResult(suggest("")))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Equal(t, []string{""}, generation.DiscardedOptimizerRunIds)
}

func TestExhaustedWaitsForScheduledRuns(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)

	// Adopt a running run so a scheduled run is outstanding when the
	// search space runs out.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// Exhausted, but the run is still going: finishing the sweep now
	// would strand it, so the loop keeps polling without asking.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	draining := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_EXHAUSTED,
		}))

	generation := draining.GetGeneration()
	require.NotNil(t, generation, "expected the loop to keep iterating")
	assert.Zero(t, generation.AskUpTo, "must not ask once exhausted")
	require.Len(t, generation.Updates, 1)

	// The run finishes: its terminal update is delivered first.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "finished", summary: `{"loss": 1}`},
	))
	terminal := fixture.step(t, emptyIterResult())
	require.Len(t, terminal.GetGeneration().Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FINISHED,
		terminal.GetGeneration().Updates[0].Run.State)

	// With nothing left in flight, the sweep is finished for real.
	fixture.stubFinishSweep()
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	done := fixture.step(t, emptyIterResult())

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_EXHAUSTED, done.GetDone().Reason)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestExhaustedWaitsForInvisibleEnqueuedRun(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 1})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, warmResult(nil))

	// A suggestion is enqueued but its run has not appeared yet.
	fixture.stubSweepConfig("RUNNING")
	fixture.stubEnqueue("backend-1")
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.step(t, generationResult(suggest("opt-1")))

	// Exhausted while that run has not appeared yet: no finish yet.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "backend-1", state: "pending"},
	))
	draining := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_EXHAUSTED,
		}))

	require.NotNil(t, draining.GetGeneration())
	assert.Zero(t, draining.GetGeneration().AskUpTo)
}
