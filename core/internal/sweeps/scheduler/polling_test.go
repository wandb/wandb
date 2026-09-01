package scheduler_test

import (
	"testing"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

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

func TestPruneLifecycle(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)

	// Adopt a running run so there is a prune candidate.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "running"},
	))
	first := fixture.step(t, warmResult(map[string]string{"victim": "opt-v"}))
	require.Equal(t, []string{"opt-v"}, first.GetGeneration().PruneCandidates)

	// The prune stops the run by its storage id; once the backend
	// accepts the stop, the run is retired immediately, freeing its
	// batch slot right away with no grace period.
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("StopRun"),
		`{"stopRun": {"success": true}}`,
	)
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	second := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{Prune: []string{"opt-v"}}))

	require.NotNil(t, second.GetGeneration())
	assert.Empty(t, second.GetGeneration().Updates)
	assert.Empty(t, second.GetGeneration().PruneCandidates)
	assert.EqualValues(t, 2, second.GetGeneration().AskUpTo)

	// The run is retired for good: even if the backend still reports
	// it running, it is never polled or told about again.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "victim", state: "running"},
	))
	third := fixture.step(t, emptyIterResult())
	assert.Empty(t, third.GetGeneration().Updates)
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

	// Absent from a complete poll: a confirming read is issued right
	// away, not after a streak of misses. Still exists: no reap.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": {"id": "node-ghost", "state": "running"}}}`,
	)
	first := fixture.step(t, emptyIterResult())
	assert.Empty(t, first.GetGeneration().Updates)

	// Absent again, and this time confirmed gone: reaped as FAILED on
	// this very poll.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": null}}`,
	)
	second := fixture.step(t, emptyIterResult())
	require.Len(t, second.GetGeneration().Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
		second.GetGeneration().Updates[0].Run.State)
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

func TestUnreadableRowReusesLastKnownState(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// A row present but with an unreadable (empty) state usually means
	// the backend and SDK have mismatched GQL schemas, not that this
	// one run is broken; the run keeps its last known state (RUNNING)
	// rather than being failed, with no confirming read needed.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: ""},
	))
	task := fixture.step(t, emptyIterResult())

	updates := task.GetGeneration().Updates
	require.Len(t, updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_RUNNING, updates[0].Run.State)
	assert.True(t, fixture.client.AllStubsUsed())
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
	fixture.clock.now = fixture.clock.now.Add(time.Hour)
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

func TestWarmStartPagesAndAdoption(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 3})
	fixture.stubPoll(pollJSON("RUNNING", true, "cursor-1",
		testRun{name: "old-finished", state: "finished",
			config:  `{"param1": {"value": 1}}`,
			summary: `{"loss": 0.5}`},
	))
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "old-running", state: "running",
			config: `{"param1": {"value": 2}}`},
	))

	pageOne := fixture.step(t, nil)
	require.NotNil(t, pageOne.GetWarmStart())
	assert.True(t, pageOne.GetWarmStart().HasMore)
	require.Len(t, pageOne.GetWarmStart().FinishedRuns, 1)
	finished := pageOne.GetWarmStart().FinishedRuns[0]
	assert.Equal(t, "old-finished", finished.WandbRunId)
	assert.JSONEq(t, `{"param1": 1}`, finished.ConfigJson)

	pageTwo := fixture.step(t, warmResult(nil))
	require.NotNil(t, pageTwo.GetWarmStart())
	assert.False(t, pageTwo.GetWarmStart().HasMore)
	require.Len(t, pageTwo.GetWarmStart().ActiveRuns, 1)

	// Adopt the running run; the first generation must update it before
	// any ask, and the ask budget must account for it.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "old-running", state: "running",
			config:  `{"param1": {"value": 2}}`,
			summary: `{"loss": 1.5}`},
	))
	generation := fixture.step(t,
		warmResult(map[string]string{"old-running": "adopted-1"}))

	task := generation.GetGeneration()
	require.NotNil(t, task)
	require.Len(t, task.Updates, 1)
	assert.Equal(t, "adopted-1", task.Updates[0].Run.OptimizerRunId)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_RUNNING, task.Updates[0].Run.State)
	assert.EqualValues(t, 2, task.AskUpTo)
	assert.Equal(t, []string{"adopted-1"}, task.PruneCandidates)
}

func TestWarmPageReclassifiesFinishedWithoutMetric(t *testing.T) {
	fixture := newLoopFixture(t,
		scheduler.SchedulerParams{MetricKey: "loss"})
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "no-metric", state: "finished", summary: `{}`},
	))

	task := fixture.step(t, nil)

	warmStart := task.GetWarmStart()
	require.NotNil(t, warmStart)
	require.Len(t, warmStart.FinishedRuns, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
		warmStart.FinishedRuns[0].State)
}

func TestWarmPageErrorSkipsRemainingWarmStart(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		&graphql.HTTPError{StatusCode: 500},
	)

	task := fixture.step(t, nil)

	// The loop proceeds to (empty) generation instead of dying.
	require.NotNil(t, task.GetGeneration())
	assert.Empty(t, task.GetGeneration().Updates)
	assert.Zero(t, task.GetGeneration().AskUpTo)
}
