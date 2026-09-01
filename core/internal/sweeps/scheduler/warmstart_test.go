package scheduler_test

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

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
