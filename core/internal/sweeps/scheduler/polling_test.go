package scheduler_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Once the search space is exhausted the sweep still has to wait out
// the runs already scheduled: finishing it early would stop the
// backend handing them to agents.
// With nothing in flight it finishes at once: see TestOptimizerFinishesTheSweep.
func TestExhaustedSearchSpaceWaitsForRunsInFlight(t *testing.T) {
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

func TestPendingRunKeepsSlot(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{
		BatchSize: 1,
	})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "stuck", state: "pending"},
	))
	fixture.step(t, warmResult(map[string]string{"stuck": "opt-s"}))

	// However long the run stays pending, it holds its slot.
	fixture.clock.now = fixture.clock.now.Add(time.Hour)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "stuck", state: "pending"},
	))
	task := fixture.step(t, emptyIterResult())

	generation := task.GetGeneration()
	require.Len(t, generation.Updates, 1)
	assert.Zero(t, generation.AskUpTo)
	// Asserted rather than left to an unstubbed call: a failed stop is
	// logged and tolerated, so only the optimizer ever ends a run early.
	assert.Empty(t, fixture.requestsFor("StopRun"),
		"the scheduler must not stop a run on its own")
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

// Every classification of a polled row, against one shared flow.
func TestPolledRowClassification(t *testing.T) {
	for name, polled := range map[string]struct {
		metricKeys  []string
		row         testRun
		wantState   spb.SweepRunState
		wantAskUpTo int
	}{
		// A row present but with an unreadable (empty) state usually means
		// the backend and SDK have mismatched GQL schemas, not that this
		// one run is broken; the run keeps its last known state (RUNNING)
		// rather than being failed, with no confirming read needed.
		"an unreadable row reuses the last known state": {
			row:         testRun{name: "run-1", state: ""},
			wantState:   spb.SweepRunState_SWEEP_RUN_STATE_RUNNING,
			wantAskUpTo: 0,
		},

		"a finish without the sweep metric is failed": {
			metricKeys: []string{"loss"},
			row: testRun{name: "run-1", state: "finished",
				summary: `{"other": 1}`},
			wantState:   spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
			wantAskUpTo: 1,
		},

		"a sweep with no metric keeps the finish": {
			row:         testRun{name: "run-1", state: "finished", summary: `{}`},
			wantState:   spb.SweepRunState_SWEEP_RUN_STATE_FINISHED,
			wantAskUpTo: 1,
		},

		// The states this build knows already cover every live one, so an
		// unrecognized value is almost certainly a terminal state added
		// since: the run is failed and frees its slot rather than being
		// waited on for the rest of the sweep.
		"an unrecognized state fails the run": {
			row:         testRun{name: "run-1", state: "hibernating"},
			wantState:   spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
			wantAskUpTo: 1,
		},
	} {
		t.Run(name, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{
				MetricKeys: polled.metricKeys,
			})
			fixture.warmTo(t)
			fixture.stubPoll(pollJSON("RUNNING", false, "",
				testRun{name: "run-1", state: "running"},
			))
			fixture.step(t, warmResult(map[string]string{"run-1": "opt-1"}))

			fixture.stubPoll(pollJSON("RUNNING", false, "", polled.row))
			task := fixture.step(t, emptyIterResult())

			generation := task.GetGeneration()
			require.NotNil(t, generation)
			require.Len(t, generation.Updates, 1)
			assert.Equal(t,
				polled.wantState, generation.Updates[0].Run.State)
			assert.EqualValues(t, polled.wantAskUpTo, generation.AskUpTo)
			assert.True(t, fixture.client.AllStubsUsed())
		})
	}
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
