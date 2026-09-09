package scheduler_test

import (
	"errors"
	"testing"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// The sweep can hold thousands of runs this scheduler neither owns nor
// acts on, so a poll reads only the ones it is still watching.
func TestPollAsksOnlyForTheWatchedRuns(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "mine", state: "running"},
		testRun{name: "stranger", state: "running"},
	))
	require.NotNil(t, fixture.step(t, nil).GetWarmStart())

	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "mine", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"mine": "opt-1"}))

	requests := fixture.requestsFor("SweepWatchedRuns")
	require.Len(t, requests, 1)
	gqlmock.AssertVariables(t, requests[0],
		gqlmock.GQLVar("filters", gomock.Eq(`{"name":{"$in":["mine"]}}`)))
}

func TestPollWithNothingToWatchReadsOnlyTheSweepState(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubIdlePoll("RUNNING")
	task := fixture.step(t, warmResult(nil))

	require.NotNil(t, task.GetGeneration())
	assert.Empty(t, fixture.requestsFor("SweepWatchedRuns"),
		"a scheduler with no runs to watch must not read any")
}

func TestPollWalksEveryPageOfTheWatchedRuns(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 3})
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
		testRun{name: "run-2", state: "running"},
	))
	require.NotNil(t, fixture.step(t, nil).GetWarmStart())

	// Stopping at the first page would make the run on the second look
	// deleted and get it reaped.
	fixture.stubPoll(pollJSON("RUNNING", true, "cursor-1",
		testRun{name: "run-1", state: "running"},
	))
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-2", state: "finished", summary: `{"loss": 1}`},
	))
	task := fixture.step(t, warmResult(map[string]string{
		"run-1": "opt-1",
		"run-2": "opt-2",
	}))

	updates := task.GetGeneration().Updates
	require.Len(t, updates, 2)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_RUNNING, updates[0].Run.State)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FINISHED, updates[1].Run.State)
	assert.True(t, fixture.client.AllStubsUsed())
}

// A dormant run that turns out to be deleted stops being read, rather
// than costing a confirming query on every later poll.
func TestDeletedDormantRunStopsBeingWatched(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// It fails, and the terminal update is acked, leaving it dormant.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "failed"},
	))
	require.Len(t, fixture.step(t, emptyIterResult()).GetGeneration().Updates, 1)

	// Now it is gone for good.
	fixture.stubPoll(pollJSON("RUNNING", false, ""))
	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("RunState"),
		`{"project": {"run": null}}`,
	)
	reaped := fixture.step(t, emptyIterResult())
	assert.Empty(t, reaped.GetGeneration().Updates)

	// Nothing left to watch, so no runs query and no confirming read.
	pollsBefore := len(fixture.requestsFor("SweepWatchedRuns"))
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, emptyIterResult())

	assert.Len(t, fixture.requestsFor("SweepWatchedRuns"), pollsBefore)
	assert.Len(t, fixture.requestsFor("RunState"), 1)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestSuggestionsEnqueueAndAppear(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)

	fixture.stubIdlePoll("RUNNING")
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
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	fixture.stubFinishSweep()
	done := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_EXHAUSTED,
		}))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
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
	fixture.stubIdlePoll("RUNNING")
	second := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{Prune: []string{"opt-v"}}))

	require.NotNil(t, second.GetGeneration())
	assert.Empty(t, second.GetGeneration().Updates)
	assert.Empty(t, second.GetGeneration().PruneCandidates)
	assert.EqualValues(t, 2, second.GetGeneration().AskUpTo)

	// The run is retired for good: it drops out of the watched set, so
	// the scheduler stops reading it at all rather than reading it and
	// discarding the row.
	fixture.stubIdlePoll("RUNNING")
	third := fixture.step(t, emptyIterResult())
	assert.Empty(t, third.GetGeneration().Updates)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestPruneIgnoresNonCandidates(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	// No StopRun stub: pruning an id that was never a candidate must
	// not call the backend.
	fixture.stubIdlePoll("RUNNING")
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

	// The states this build knows already cover every live one, so an
	// unrecognized value is almost certainly a terminal state added
	// since: the run is failed and frees its slot rather than being
	// waited on for the rest of the sweep.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "hibernating"},
	))
	task := fixture.step(t, emptyIterResult())

	generation := task.GetGeneration()
	updates := generation.Updates
	require.Len(t, updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED, updates[0].Run.State)
	assert.EqualValues(t, 1, generation.AskUpTo)
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

	fixture.stubIdlePoll("PAUSED")
	task := fixture.step(t, warmResult(nil))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Empty(t, generation.Updates)
	assert.Zero(t, generation.AskUpTo)
}

func TestExternallyFinishedSweepEndsLoop(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubIdlePoll("FINISHED")
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		done.GetDone().Reason)
}

func TestCanceledSweepEndsLoopAsTerminated(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubIdlePoll("CANCELED")
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_TERMINATED,
		done.GetDone().Reason)
}

func TestFlappingSweepEndsLoopAsFatalError(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	// The backend, not the user, gave up on the sweep.
	fixture.stubIdlePoll("FLAPPING")
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
		done.GetDone().Reason)
}

func TestUnrecognizedSweepStateKeepsScheduling(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 1})
	fixture.warmTo(t)

	// A state this build does not know is not a done state, so the loop
	// keeps scheduling instead of reporting the sweep terminated.
	fixture.stubIdlePoll("SOME_NEW_ACTIVE_STATE")
	task := fixture.step(t, warmResult(nil))

	require.NotNil(t, task.GetGeneration())
	assert.EqualValues(t, 1, task.GetGeneration().AskUpTo)
}

func TestLateSuggestionsDiscardedWhenSweepFinished(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
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

	fixture.client.StubMatchOnce(
		gqlmock.WithOpName("SweepConfig"),
		`{"project": {"sweep": null}}`,
	)
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
		gqlmock.WithOpName("SweepConfig"),
		&graphql.HTTPError{StatusCode: 403},
	)
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
		done.GetDone().Reason)
}

func TestPollErrorEndsTheScheduler(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	// The HTTP client has already retried a 502 by the time the loop
	// sees it, so polling again is not what would make it succeed.
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepConfig"),
		&graphql.HTTPError{StatusCode: 502},
	)
	task := fixture.step(t, emptyIterResult())

	done := task.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
}

func TestRateLimitedPollKeepsGoing(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepConfig"),
		&graphql.HTTPError{StatusCode: 429},
	)
	task := fixture.step(t, emptyIterResult())

	// An empty task while the backend asks for a slower pace.
	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Empty(t, generation.Updates)
}

func TestRateLimitedEnqueueDiscardsAndContinues(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	// A rate limit costs only this suggestion; the loop slows down and
	// carries on.
	fixture.stubSweepConfig("RUNNING")
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("EnqueueSweepRun"),
		&graphql.HTTPError{StatusCode: 429},
	)
	// The suggestion never became a run, so there is nothing to watch.
	fixture.stubIdlePoll("RUNNING")
	task := fixture.step(t, generationResult(suggest("opt-lost")))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	// The discard rides the next task so the optimizer still forgets
	// the suggestion.
	assert.Equal(t,
		[]string{"opt-lost"}, generation.DiscardedOptimizerRunIds)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestFatalEnqueueFailureEndsTheSchedulerWithTheDiscard(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	// A 400 is never retried, so polling again cannot help.
	fixture.stubSweepConfig("RUNNING")
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("EnqueueSweepRun"),
		&graphql.HTTPError{StatusCode: 400},
	)
	task := fixture.step(t, generationResult(suggest("opt-lost")))

	done := task.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR, done.Reason)
	// The discard rides the Done task so the optimizer still forgets
	// the suggestion.
	assert.Equal(t,
		[]string{"opt-lost"}, done.DiscardedOptimizerRunIds)
}

func TestSuggestionsAfterAFatalEnqueueAreDiscarded(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 3})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	// Only the first suggestion is attempted; the rest are never
	// enqueued, so the Done must carry all three ids or the optimizer
	// waits forever for runs that will not happen.
	fixture.stubSweepConfig("RUNNING")
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("EnqueueSweepRun"),
		&graphql.HTTPError{StatusCode: 400},
	)
	task := fixture.step(t,
		generationResult(suggest("opt-1", "opt-2", "opt-3")))

	done := task.GetDone()
	require.NotNil(t, done)
	assert.Equal(t,
		[]string{"opt-1", "opt-2", "opt-3"},
		done.DiscardedOptimizerRunIds)
}

func TestDuplicateSuggestionIDDroppedWithoutDiscarding(t *testing.T) {
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
	// Reporting the id would make the client forget the run that owns
	// it, and its update in this very task would then fail.
	assert.Empty(t, generation.DiscardedOptimizerRunIds)
	require.Len(t, generation.Updates, 1)
	assert.Equal(t, "opt-1", generation.Updates[0].Run.OptimizerRunId)
}

func TestEnqueuedRunDeletedBeforeAppearingIsReaped(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
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
	fixture.stubIdlePoll("RUNNING")
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

func TestSucceededRunIsDroppedFromTheWatchedSet(t *testing.T) {
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

	// Its result is valid and final, so it is never read again. A resume
	// after this point cannot improve on what the optimizer already has.
	fixture.stubIdlePoll("RUNNING")
	settled := fixture.step(t, emptyIterResult())

	generation := settled.GetGeneration()
	assert.Empty(t, generation.Updates)
	assert.EqualValues(t, 2, generation.AskUpTo)
	assert.True(t, fixture.client.AllStubsUsed())
}

// A run that ended badly stays readable so a resume can be reported to
// the user, but it is never told to the optimizer again: both optimizers
// finalize a trial on its terminal tell and ignore every later one, so a
// re-tell would teach the search nothing while costing a batch slot.
func TestResumedRunIsNotRetoldNorCounted(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	// It crashes; the terminal update is delivered and acked, freeing
	// its batch slot.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "crashed"},
	))
	crashed := fixture.step(t, emptyIterResult())
	require.Len(t, crashed.GetGeneration().Updates, 1)
	assert.EqualValues(t, 2, crashed.GetGeneration().AskUpTo)

	// It resumes: still read, but no second tell and no slot reclaimed.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	resumed := fixture.step(t, emptyIterResult())
	assert.Empty(t, resumed.GetGeneration().Updates)
	assert.EqualValues(t, 2, resumed.GetGeneration().AskUpTo)

	// Not even if it goes on to finish: the trial is already closed.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "finished", summary: `{"loss": 1}`},
	))
	finished := fixture.step(t, emptyIterResult())
	assert.Empty(t, finished.GetGeneration().Updates)
	assert.EqualValues(t, 2, finished.GetGeneration().AskUpTo)
	assert.True(t, fixture.client.AllStubsUsed())
}

// PREEMPTED is terminal here because it is terminal on the client: both
// optimizers see RunState.PREEMPTED as dead and fail the trial on the
// first tell. Holding the slot open would strand the batch.
func TestPreemptedRunIsTerminalAndFreesItsSlot(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 1})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "preempted"},
	))
	task := fixture.step(t, emptyIterResult())

	generation := task.GetGeneration()
	require.Len(t, generation.Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_PREEMPTED,
		generation.Updates[0].Run.State)

	// The slot is released once the client acks, so a batch of one can
	// schedule again instead of deadlocking.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "preempted"},
	))
	next := fixture.step(t, emptyIterResult())
	assert.EqualValues(t, 1, next.GetGeneration().AskUpTo)
}

func TestEmptySuggestionIDDroppedWithoutDiscarding(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	// An empty id would join to any run without a display name, so the
	// suggestion is dropped before it is enqueued (no enqueue stub).
	fixture.stubSweepConfig("RUNNING")
	fixture.stubIdlePoll("RUNNING")
	task := fixture.step(t, generationResult(suggest("")))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	// An empty id names no run for the client to forget.
	assert.Empty(t, generation.DiscardedOptimizerRunIds)
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
	fixture.stubIdlePoll("RUNNING")
	done := fixture.step(t, emptyIterResult())

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED, done.GetDone().Reason)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestExhaustedWaitsForInvisibleEnqueuedRun(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 1})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
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
	fixture.stubWarmStart(warmJSON("RUNNING", true, "cursor-1",
		testRun{name: "old-finished", state: "finished",
			config:  `{"param1": {"value": 1}}`,
			summary: `{"loss": 0.5}`},
	))
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
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
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
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

func TestRateLimitedWarmPageRetriesThePage(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		&graphql.HTTPError{StatusCode: 429},
	)

	task := fixture.step(t, nil)

	// Still warm-starting: skipping the page would start the search
	// cold over the runs it covers.
	warmStart := task.GetWarmStart()
	require.NotNil(t, warmStart)
	assert.Empty(t, warmStart.FinishedRuns)
	assert.Empty(t, warmStart.ActiveRuns)
	assert.True(t, warmStart.HasMore)

	// The retry re-reads the page, and its runs reach the optimizer.
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "prior-1", state: "finished"},
	))
	retried := fixture.step(t, warmResult(nil))

	warmStart = retried.GetWarmStart()
	require.NotNil(t, warmStart)
	require.Len(t, warmStart.FinishedRuns, 1)
	assert.Equal(t, "prior-1", warmStart.FinishedRuns[0].WandbRunId)
	assert.False(t, warmStart.HasMore)
	assert.True(t, fixture.client.AllStubsUsed())
}

func TestWarmStartFinishedRunReachesRunCap(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{RunCap: 1})

	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "old-finished", state: "finished", summary: `{"loss": 1}`},
	))
	warm := fixture.step(t, nil)
	require.Len(t, warm.GetWarmStart().FinishedRuns, 1)

	// The cap was already reached by the warm-started run alone.
	fixture.stubIdlePoll("RUNNING")
	done := fixture.step(t, warmResult(nil))

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		done.GetDone().Reason)
	assert.Contains(t, done.GetDone().Message, "run cap")
}

func TestFailedWarmStartRunDoesNotCountTowardRunCap(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{RunCap: 1})

	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "old-failed", state: "failed"},
	))
	warm := fixture.step(t, nil)
	require.Len(t, warm.GetWarmStart().FinishedRuns, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
		warm.GetWarmStart().FinishedRuns[0].State)

	// A failed run never counts toward the cap: the loop keeps going.
	fixture.stubIdlePoll("RUNNING")
	task := fixture.step(t, warmResult(nil))

	require.NotNil(t, task.GetGeneration())
}

func TestRunCapAccountsForRunsFinishedDuringPolling(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{RunCap: 2})

	// One prior run already finished by warm start.
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "old-finished", state: "finished", summary: `{"loss": 1}`},
	))
	warm := fixture.step(t, nil)
	require.Len(t, warm.GetWarmStart().FinishedRuns, 1)

	// Adopt a running run so a second run can finish under pollAll.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
	))
	generation := fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))
	require.NotNil(t, generation.GetGeneration())

	// run-1 finishes: the cap is now reached, but its terminal update is
	// still delivered before the loop notices next step.
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "finished", summary: `{"loss": 1}`},
	))
	terminal := fixture.step(t, emptyIterResult())
	require.Len(t, terminal.GetGeneration().Updates, 1)
	assert.Equal(t,
		spb.SweepRunState_SWEEP_RUN_STATE_FINISHED,
		terminal.GetGeneration().Updates[0].Run.State)

	// The next step sees the cap reached and ends the sweep.
	fixture.stubIdlePoll("RUNNING")
	done := fixture.step(t, emptyIterResult())

	require.NotNil(t, done.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		done.GetDone().Reason)
	assert.Contains(t, done.GetDone().Message, "run cap")
}

func TestWarmPageErrorEndsTheScheduler(t *testing.T) {
	// Only a rate limit leaves the page worth re-reading; everything
	// else has already outlived the HTTP client's retries. An empty
	// warm-start task would tell the optimizer this page held no prior
	// runs, so it must never stand in for one of these.
	for name, err := range map[string]error{
		"server error":    &graphql.HTTPError{StatusCode: 500},
		"forbidden":       &graphql.HTTPError{StatusCode: 403},
		"bad request":     &graphql.HTTPError{StatusCode: 400},
		"retries used up": errors.New("giving up after 20 attempt(s)"),
	} {
		t.Run(name, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{})
			fixture.client.StubMatchWithError(
				gqlmock.WithOpName("SweepRunsWithHistory"), err)

			task := fixture.step(t, nil)

			require.Nil(t, task.GetWarmStart(),
				"warm start reported an empty page for an unretryable error")
			done := task.GetDone()
			require.NotNil(t, done, "warm start retried an unretryable page")
			assert.Equal(t,
				spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				done.Reason)
		})
	}
}
