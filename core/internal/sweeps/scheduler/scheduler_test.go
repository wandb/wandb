package scheduler_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeClock lets tests control the scheduler's notion of now and fires
// every timer immediately so failure slowdowns cost no test time.
type fakeClock struct {
	now time.Time

	// waiting, when non-nil, holds every timer open and announces it
	// here, so a test can act while the loop is inside its wait.
	waiting chan struct{}
}

func (c *fakeClock) Now() time.Time { return c.now }

func (c *fakeClock) NewTimer(time.Duration) (<-chan time.Time, func()) {
	if c.waiting != nil {
		c.waiting <- struct{}{}
		return make(chan time.Time), func() {}
	}

	fire := make(chan time.Time, 1)
	fire <- time.Time{}
	return fire, func() {}
}

var (
	_ scheduler.Clock = (*fakeClock)(nil)
)

func TestRealClockNowIsWallClockTime(t *testing.T) {
	before := time.Now()
	now := scheduler.RealClock{}.Now()
	after := time.Now()

	assert.False(t, now.Before(before))
	assert.False(t, now.After(after))
}

func TestRealClockNewTimerFiresAfterTheDuration(t *testing.T) {
	fire, stop := scheduler.RealClock{}.NewTimer(10 * time.Millisecond)
	defer stop()

	select {
	case <-fire:
	case <-time.After(time.Second):
		t.Fatal("timer did not fire")
	}
}

func TestFakeClockNewTimerFiresImmediately(t *testing.T) {
	clock := &fakeClock{now: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)}

	fire, stop := clock.NewTimer(time.Hour)
	defer stop()

	select {
	case <-fire:
	default:
		t.Fatal("expected the fake timer to have already fired")
	}
}

// testRun scripts one poll row.
type testRun struct {
	name    string
	state   string
	config  string // wire form; "" means {}
	summary string
	history string
}

// runConnection builds the runs connection both run queries return.
func runConnection(hasNext bool, cursor string, runs []testRun) map[string]any {
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

	return map[string]any{
		"pageInfo": map[string]any{
			"hasNextPage": hasNext,
			"endCursor":   orNil(cursor),
		},
		"edges": edges,
	}
}

func encodeJSON(response map[string]any) string {
	encoded, err := json.Marshal(response)
	if err != nil {
		panic(err)
	}
	return string(encoded)
}

// warmJSON builds a SweepRunsWithHistory response: one page of every
// run in the sweep.
func warmJSON(sweepState string, hasNext bool, cursor string, runs ...testRun) string {
	return encodeJSON(map[string]any{
		"project": map[string]any{
			"sweep": map[string]any{
				"state": sweepState,
				"runs":  runConnection(hasNext, cursor, runs),
			},
		},
	})
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
	if params.Logger == nil {
		params.Logger = observability.NewNoOpLogger()
	}
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

// stubIdlePoll answers one generation poll made with nothing to watch,
// which reads only the sweep's state.
func (f *loopFixture) stubIdlePoll(sweepState string) {
	f.stubSweepConfig(sweepState)
}

// stubWarmStart answers one warm-start page.
func (f *loopFixture) stubWarmStart(response string) {
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

// stubFinishSweep answers the loop's request to finish the sweep.
func (f *loopFixture) stubFinishSweep() {
	f.client.StubMatchOnce(
		gqlmock.WithOpName("UpsertSweepState"),
		`{"upsertSweep": {"sweep": {"state": "FINISHED"}}}`,
	)
}

// requestsFor returns every request made for the named operation.
func (f *loopFixture) requestsFor(opName string) []*graphql.Request {
	var found []*graphql.Request
	for _, req := range f.client.AllRequests() {
		if req.OpName == opName {
			found = append(found, req)
		}
	}
	return found
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

// warmTo drives one Step with no prior result, to set up the scheduler
// for a test's own step(s).
func (f *loopFixture) warmTo(t *testing.T) {
	t.Helper()
	f.stubWarmStart(warmJSON("RUNNING", false, ""))
	task := f.step(t, nil)
	require.NotNil(t, task.GetWarmStart(),
		"expected the warm start to complete")
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

func emptyIterResult() *spb.SweepSchedulerClientTaskResult {
	return generationResult(&spb.SweepSchedulerClientGenerationResult{})
}

func TestStopDuringPollExitsWithoutAsking(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	fixture.client.StubMatchHang(gqlmock.WithOpName("SweepConfig"))

	pollsBefore := len(fixture.requestsFor("SweepConfig"))
	done := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		done <- fixture.scheduler.Step(context.Background(), emptyIterResult())
	}()

	require.Eventually(t, func() bool {
		return len(fixture.requestsFor("SweepConfig")) > pollsBefore
	}, 2*time.Second, 10*time.Millisecond)

	fixture.scheduler.Stop()

	task := schedulertest.Receive(t, done)
	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
	// Asserted rather than left to an unstubbed call: finishSweep only
	// warns on failure, so a stop that wrongly finished the sweep would
	// go unnoticed here. A stopped sweep has to stay resumable.
	assert.Empty(t, fixture.requestsFor("UpsertSweepState"),
		"a stop must not transition the sweep")
}

// A stop can also land while the loop is waiting out its poll
// interval, which leaves sleep by its other exit. It must end the
// session just as cleanly, and leave the sweep just as resumable.
func TestStopDuringTheWaitExitsWithoutTransitioningTheSweep(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	// Held open, so the loop is provably inside the wait when it stops.
	fixture.clock.waiting = make(chan struct{}, 1)

	done := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		done <- fixture.scheduler.Step(context.Background(), warmResult(nil))
	}()

	<-fixture.clock.waiting
	fixture.scheduler.Stop()

	task := schedulertest.Receive(t, done)
	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
	assert.Empty(t, fixture.requestsFor("SweepConfig"),
		"a stop during the wait must not go on to poll")
	assert.Empty(t, fixture.requestsFor("UpsertSweepState"),
		"a stop must not transition the sweep")
}

func TestSessionCancelReturnsShutdown(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	fixture.stubWarmStart(warmJSON("RUNNING", false, ""))
	task := fixture.scheduler.Step(ctx, nil)

	// The warm-start page may complete, but the following step's sleep
	// observes the cancelled context.
	if task.GetWarmStart() != nil {
		task = fixture.scheduler.Step(ctx, warmResult(nil))
	}
	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		task.GetDone().Reason)
	// Asserted rather than left to an unstubbed call: finishSweep only
	// warns on failure, so a shutdown that wrongly finished the sweep
	// would go unnoticed. A sweep whose scheduler went away has to stay
	// resumable.
	assert.Empty(t, fixture.requestsFor("UpsertSweepState"),
		"a shutdown must not transition the sweep")
}

// A negative bound cannot be honoured, and guessing what it meant would
// silently cap or uncap the sweep, so it is dropped with a warning and
// the scheduler carries on with the bound unset.
func TestNegativeBoundsAreIgnoredWithAWarning(t *testing.T) {
	for name, params := range map[string]scheduler.SchedulerParams{
		"batch size": {BatchSize: -4},
		"run cap":    {RunCap: -10},
	} {
		t.Run("a negative "+name, func(t *testing.T) {
			logger, logs := observabilitytest.NewRecordingTestLogger(t)
			params.Logger = logger
			fixture := newLoopFixture(t, params)
			fixture.stubWarmStart(warmJSON("RUNNING", false, "",
				testRun{name: "run-1", state: "running"},
			))

			task := fixture.step(t, nil)

			assert.Contains(t, logs.String(), `"level":"WARN"`)
			assert.Contains(t, logs.String(), name)
			require.NotNil(t, task.GetWarmStart(),
				"the scheduler must still run with the bound unset")
		})
	}
}

// The sweep can hold thousands of runs this scheduler neither owns nor
// acts on, so a generation that watches none of them reads only the
// sweep's state.
func TestGenerationWithNothingToWatchReadsOnlyTheSweepState(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)

	fixture.stubIdlePoll("RUNNING")
	task := fixture.step(t, warmResult(nil))

	generation := task.GetGeneration()
	require.NotNil(t, generation)
	assert.Empty(t, generation.Updates)
	assert.EqualValues(t, 2, generation.AskUpTo,
		"the whole batch is free, so the ask is the batch size")
	assert.Empty(t, fixture.requestsFor("SweepWatchedRuns"),
		"a scheduler with no runs to watch must not read any")
	assert.True(t, fixture.client.AllStubsUsed())
}

// What a poll finds the sweep in decides whether the loop keeps
// scheduling, idles, or ends — and with which reason.
func TestGenerationFollowsTheSweepState(t *testing.T) {
	// nil reason means the loop keeps going with a generation task.
	done := func(
		reason spb.SweepSchedulerServerDoneTask_Reason,
	) *spb.SweepSchedulerServerDoneTask_Reason {
		return &reason
	}
	for state, reason := range map[string]*spb.SweepSchedulerServerDoneTask_Reason{
		"RUNNING":  nil,
		"PAUSED":   nil,
		"PENDING":  nil,
		"GARBLED":  nil, // a state this build does not know
		"FINISHED": done(spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED),
		"CANCELED": done(spb.SweepSchedulerServerDoneTask_REASON_TERMINATED),
		"ERROR":    done(spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR),
		"FLAPPING": done(spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR),
		"CRASHED":  done(spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR),
	} {
		t.Run(state, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 1})
			fixture.warmTo(t)

			fixture.stubIdlePoll(state)
			task := fixture.step(t, warmResult(nil))

			if reason == nil {
				generation := task.GetGeneration()
				require.NotNil(t, generation,
					"the loop must keep scheduling under %q", state)
				if state == "PAUSED" {
					// Running runs stay alive, but nothing new starts.
					assert.Zero(t, generation.AskUpTo)
				} else {
					assert.EqualValues(t, 1, generation.AskUpTo)
				}
				return
			}
			require.NotNil(t, task.GetDone())
			assert.Equal(t, *reason, task.GetDone().Reason)
		})
	}
}

// Whatever a poll finds, the scheduler reports it without writing it
// back. Only its own decisions -- an exhausted search space, the run
// cap, a terminate -- finish a sweep; a sweep the user cancelled or a
// backend failure must be left exactly as found, so nothing overwrites
// the state that explains what happened.
func TestGenerationNeverWritesBackTheSweepState(t *testing.T) {
	for _, state := range []string{
		"RUNNING", "PAUSED", "GARBLED",
		"FINISHED", "CANCELED", "ERROR", "FLAPPING", "CRASHED",
	} {
		t.Run(state, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 1})
			fixture.warmTo(t)

			fixture.stubIdlePoll(state)
			require.NotNil(t, fixture.step(t, warmResult(nil)))

			// Asserted rather than left to an unstubbed call: finishSweep
			// only warns on failure, so a stray transition would be
			// invisible here.
			assert.Empty(t, fixture.requestsFor("UpsertSweepState"),
				"a polled state must not be written back")
		})
	}
}

// A poll that fails ends the sweep unless polling again is what would
// fix it: the HTTP client has already retried by the time the loop sees
// the error, so only a rate limit is worth another pass.
func TestGenerationPollFailures(t *testing.T) {
	fixture := func(t *testing.T) *loopFixture {
		t.Helper()
		f := newLoopFixture(t, scheduler.SchedulerParams{})
		f.warmTo(t)
		return f
	}

	t.Run("a deleted sweep ends the loop", func(t *testing.T) {
		f := fixture(t)
		f.client.StubMatchOnce(
			gqlmock.WithOpName("SweepConfig"),
			`{"project": {"sweep": null}}`,
		)

		task := f.step(t, warmResult(nil))

		require.NotNil(t, task.GetDone())
		assert.Equal(t,
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_NOT_FOUND,
			task.GetDone().Reason)
	})

	for name, err := range map[string]error{
		"forbidden":       &graphql.HTTPError{StatusCode: 403},
		"bad gateway":     &graphql.HTTPError{StatusCode: 502},
		"retries used up": errors.New("giving up after 20 attempt(s)"),
	} {
		t.Run(name+" ends the loop", func(t *testing.T) {
			f := fixture(t)
			f.client.StubMatchWithError(gqlmock.WithOpName("SweepConfig"), err)

			task := f.step(t, warmResult(nil))

			require.NotNil(t, task.GetDone())
			assert.Equal(t,
				spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				task.GetDone().Reason)
		})
	}

	t.Run("a rate limit keeps the loop going", func(t *testing.T) {
		f := fixture(t)
		f.client.StubMatchWithError(
			gqlmock.WithOpName("SweepConfig"),
			&graphql.HTTPError{StatusCode: 429},
		)

		task := f.step(t, warmResult(nil))

		// An empty task while the backend asks for a slower pace.
		generation := task.GetGeneration()
		require.NotNil(t, generation)
		assert.Empty(t, generation.Updates)
		assert.Zero(t, generation.AskUpTo)
	})
}

// The run cap counts the sweep's successes, including the ones warm
// start replayed, and ends the sweep once it is reached.
func TestGenerationEndsTheSweepAtTheRunCap(t *testing.T) {
	for _, prior := range []struct {
		state   string
		summary string
		capHit  bool
	}{
		{state: "finished", summary: `{"loss": 1}`, capHit: true},
		{state: "failed", capHit: false},
		{state: "crashed", capHit: false},
	} {
		t.Run(prior.state, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{RunCap: 1})
			fixture.stubWarmStart(warmJSON("RUNNING", false, "",
				testRun{name: "old", state: prior.state, summary: prior.summary},
			))
			warm := fixture.step(t, nil)
			require.Len(t, warm.GetWarmStart().FinishedRuns, 1)

			fixture.stubIdlePoll("RUNNING")
			if prior.capHit {
				// Finishing the sweep is what hitting the cap does.
				fixture.stubFinishSweep()
			}
			task := fixture.step(t, warmResult(nil))

			if !prior.capHit {
				require.NotNil(t, task.GetGeneration(),
					"a run that did not succeed must not count")
				return
			}
			require.NotNil(t, task.GetDone())
			assert.Equal(t,
				spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
				task.GetDone().Reason)
			assert.Contains(t, task.GetDone().Message, "run cap")
			assert.True(t, fixture.client.AllStubsUsed())
		})
	}
}

// Red until results are applied: the next slice gives each of these an
// effect. Until then a result is ignored and the loop just polls again,
// which is what this asserts.
func TestTaskResultsAreNotAppliedYet(t *testing.T) {
	for name, result := range map[string]*spb.SweepSchedulerClientTaskResult{
		"an adoption": warmResult(map[string]string{"old": "opt-1"}),
		"a terminate": generationResult(
			&spb.SweepSchedulerClientGenerationResult{Terminate: true}),
		"an optimizer error": {
			Result: &spb.SweepSchedulerClientTaskResult_Error{
				Error: &spb.SweepSchedulerClientTaskError{
					Message: "the optimizer exploded",
				},
			},
		},
		"a tell error": generationResult(
			&spb.SweepSchedulerClientGenerationResult{
				TellErrors: []*spb.SweepSchedulerClientTellError{
					{OptimizerRunId: "opt-p", Message: "bad summary"},
				},
			}),
	} {
		t.Run(name, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{})
			fixture.warmTo(t)

			// No UpsertSweepState stub: ending the sweep here would fail
			// the test on an unstubbed call.
			fixture.stubIdlePoll("RUNNING")
			task := fixture.step(t, result)

			require.NotNil(t, task.GetGeneration(),
				"the result must have no effect until applyResult lands")
		})
	}
}

// byRunID indexes a warm-start bucket for assertions that name a run.
func byRunID(
	runs []*spb.SweepSchedulerServerRunData,
) map[string]*spb.SweepSchedulerServerRunData {
	byID := make(map[string]*spb.SweepSchedulerServerRunData, len(runs))
	for _, run := range runs {
		byID[run.WandbRunId] = run
	}
	return byID
}

// One page carrying every kind of prior run, so each classification is
// asserted against the same read.
func TestWarmStartPageClassifiesEveryPriorRun(t *testing.T) {
	fixture := newLoopFixture(t,
		scheduler.SchedulerParams{MetricKeys: []string{"loss"}})
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "scored", state: "finished",
			config:  `{"lr": {"value": 0.1}}`,
			summary: `{"loss": 0.5}`,
			history: `[{"loss": 0.9, "_step": 1}]`},
		testRun{name: "unscored", state: "finished",
			config:  `{"lr": {"value": 0.2}}`,
			summary: `{}`},
		testRun{name: "live", state: "running",
			config: `{"lr": {"value": 0.3}}`},
		testRun{name: "mystery", state: "teleporting"},
	))

	task := fixture.step(t, nil)

	warmStart := task.GetWarmStart()
	require.NotNil(t, warmStart)
	finished := byRunID(warmStart.FinishedRuns)
	active := byRunID(warmStart.ActiveRuns)

	t.Run("a scored run carries its summary and sampled history", func(t *testing.T) {
		run := finished["scored"]
		require.NotNil(t, run)
		assert.Equal(t, spb.SweepRunState_SWEEP_RUN_STATE_FINISHED, run.State)
		assert.JSONEq(t, `{"loss": 0.5}`, run.SummaryJson)
		assert.JSONEq(t, `[{"loss": 0.9, "_step": 1}]`, run.HistoryJson)
	})

	t.Run("the wire config is flattened", func(t *testing.T) {
		require.NotNil(t, finished["scored"])
		assert.JSONEq(t, `{"lr": 0.1}`, finished["scored"].ConfigJson)
		require.NotNil(t, active["live"])
		assert.JSONEq(t, `{"lr": 0.3}`, active["live"].ConfigJson)
	})

	t.Run("a run that finished without the objective is failed", func(t *testing.T) {
		run := finished["unscored"]
		require.NotNil(t, run, "a reclassified run belongs with the finished runs")
		assert.Equal(t, spb.SweepRunState_SWEEP_RUN_STATE_FAILED, run.State)
	})

	t.Run("an unrecognized state is failed", func(t *testing.T) {
		run := finished["mystery"]
		require.NotNil(t, run)
		assert.Equal(t, spb.SweepRunState_SWEEP_RUN_STATE_FAILED, run.State)
	})

	t.Run("a live run is active and unscored", func(t *testing.T) {
		run := active["live"]
		require.NotNil(t, run)
		assert.Equal(t, spb.SweepRunState_SWEEP_RUN_STATE_RUNNING, run.State)
		// A run still going has no result to report.
		assert.Empty(t, run.SummaryJson)
		assert.Empty(t, run.HistoryJson)
	})

	t.Run("one page with no next cursor is the whole walk", func(t *testing.T) {
		assert.False(t, warmStart.HasMore)
		assert.True(t, fixture.client.AllStubsUsed())
	})
}

// Both pages of one walk, driven in order against the same scheduler.
func TestWarmStartWalksEveryPage(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.stubWarmStart(warmJSON("RUNNING", true, "cursor-1",
		testRun{name: "old-finished", state: "finished",
			summary: `{"loss": 0.5}`},
	))
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "old-running", state: "running"},
	))

	t.Run("the first page reports more to come", func(t *testing.T) {
		pageOne := fixture.step(t, nil).GetWarmStart()
		require.NotNil(t, pageOne)
		assert.True(t, pageOne.HasMore)
		require.Len(t, pageOne.FinishedRuns, 1)
		assert.Equal(t, "old-finished", pageOne.FinishedRuns[0].WandbRunId)
	})

	t.Run("the next page resumes from the cursor and ends the walk", func(t *testing.T) {
		pageTwo := fixture.step(t, warmResult(nil)).GetWarmStart()
		require.NotNil(t, pageTwo)
		assert.False(t, pageTwo.HasMore)
		require.Len(t, pageTwo.ActiveRuns, 1)
		assert.Equal(t, "old-running", pageTwo.ActiveRuns[0].WandbRunId)
		assert.True(t, fixture.client.AllStubsUsed())
	})
}

func TestRateLimitedWarmPageRetriesThePage(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		&graphql.HTTPError{StatusCode: 429},
	)

	t.Run("the rate-limited page reports no prior runs", func(t *testing.T) {
		// Still warm-starting: skipping the page would start the search
		// cold over the runs it covers.
		warmStart := fixture.step(t, nil).GetWarmStart()
		require.NotNil(t, warmStart)
		assert.Empty(t, warmStart.FinishedRuns)
		assert.Empty(t, warmStart.ActiveRuns)
		assert.True(t, warmStart.HasMore)
	})

	t.Run("the retry re-reads it and its runs reach the optimizer", func(t *testing.T) {
		fixture.stubWarmStart(warmJSON("RUNNING", false, "",
			testRun{name: "prior-1", state: "finished"},
		))

		warmStart := fixture.step(t, warmResult(nil)).GetWarmStart()
		require.NotNil(t, warmStart)
		require.Len(t, warmStart.FinishedRuns, 1)
		assert.Equal(t, "prior-1", warmStart.FinishedRuns[0].WandbRunId)
		assert.False(t, warmStart.HasMore)
		assert.True(t, fixture.client.AllStubsUsed())
	})
}

func TestWarmStartEndsForASweepThatIsDone(t *testing.T) {
	// How the sweep ended is what the Done task reports, so each state
	// the scheduler cannot schedule under maps to its own reason.
	for state, reason := range map[string]spb.SweepSchedulerServerDoneTask_Reason{
		"FINISHED": spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		"CANCELED": spb.SweepSchedulerServerDoneTask_REASON_TERMINATED,
		"ERROR":    spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
		"FLAPPING": spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
		"CRASHED":  spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
	} {
		t.Run(state, func(t *testing.T) {
			fixture := newLoopFixture(t, scheduler.SchedulerParams{})
			fixture.stubWarmStart(warmJSON(state, false, "",
				testRun{name: "prior-1", state: "finished"},
			))

			task := fixture.step(t, nil)

			require.Nil(t, task.GetWarmStart(),
				"a sweep that is done must not be replayed")
			require.NotNil(t, task.GetDone())
			assert.Equal(t, reason, task.GetDone().Reason)
			assert.Contains(t, task.GetDone().Message, state)
		})
	}
}

func TestWarmPageErrorEndsTheScheduler(t *testing.T) {
	// Only a rate limit leaves the page worth re-reading; everything
	// else has already outlived the HTTP client's retries. An empty
	// warm-start task would tell the optimizer this page held no prior
	// runs, so it must never stand in for one of these.
	//
	// Which statuses are fatal is TestClassify's contract.
	for name, err := range map[string]error{
		"server error":    &graphql.HTTPError{StatusCode: 500},
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

// factoryFixture hands the session factory a SweepAPI over a mock
// backend, so a session starts without a real client.
type factoryFixture struct {
	client                *gqlmock.MockClient
	localSchedulerEnabled bool
}

func newFactoryFixture() *factoryFixture {
	return &factoryFixture{
		client:                gqlmock.NewMockClient(),
		localSchedulerEnabled: true,
	}
}

// stubSweep answers the sweep fetch with a sweep carrying configYAML.
func (f *factoryFixture) stubSweep(configYAML string) {
	f.client.StubMatchOnce(
		gqlmock.WithOpName("SweepConfig"),
		encodeJSON(map[string]any{
			"project": map[string]any{
				"sweep": map[string]any{
					"id":                "sweep-node-id",
					"state":             "RUNNING",
					"config":            configYAML,
					"displayName":       "loss-sweep",
					"controllerRunName": "sweep-controller-run",
				},
			},
		}))
}

// stubMissingSweep answers the sweep fetch as the backend does for a
// sweep that does not exist.
func (f *factoryFixture) stubMissingSweep() {
	f.client.StubMatchOnce(
		gqlmock.WithOpName("SweepConfig"),
		encodeJSON(map[string]any{"project": nil}))
}

// startSession runs the factory over a SweepAPI on the mock backend,
// as the session broker does with the one it opens per sweep.
func (f *factoryFixture) startSession(t *testing.T) (
	scheduler.TaskResolver,
	*spb.SweepSchedulerServerInitResponse,
	error,
) {
	t.Helper()

	sweepAPI := scheduler.NewSweepAPI(
		f.client,
		featurechecker.NewPreloaded(map[spb.ServerFeature]bool{
			spb.ServerFeature_SWEEPS_LOCAL_SCHEDULER: f.localSchedulerEnabled,
		}),
		"test-entity", "test-project", "test-sweep",
	)

	factory := scheduler.NewTaskResolverFactory(observability.NewNoOpLogger())
	return factory(
		context.Background(),
		t.Context(),
		&spb.SweepSchedulerClientInitRequest{
			Entity:              "test-entity",
			Project:             "test-project",
			SweepId:             "test-sweep",
			BatchSize:           2,
			PollIntervalSeconds: 5,
		},
		sweepAPI)
}

func TestFactoryStartsASession(t *testing.T) {
	t.Run("single objective", func(t *testing.T) {
		fixture := newFactoryFixture()
		fixture.stubSweep("metric:\n  name: loss\nrun_cap: 10\n")

		resolver, init, err := fixture.startSession(t)

		require.NoError(t, err)
		assert.NotNil(t, resolver)
		assert.Equal(t, "metric:\n  name: loss\nrun_cap: 10\n", init.SweepConfig)
		assert.Equal(t, "loss-sweep", init.DisplayName)
		assert.Equal(t, "sweep-controller-run", init.ControllerRunName)
	})

	t.Run("multi objective", func(t *testing.T) {
		fixture := newFactoryFixture()
		fixture.stubSweep("metrics:\n  - name: loss\n  - name: latency\n")

		resolver, _, err := fixture.startSession(t)

		require.NoError(t, err)
		assert.NotNil(t, resolver)
	})
}

// TestFactoryRefuses covers the ways starting a session can fail, all of
// which follow the same flow: stub the backend one way, start the
// session, and check the error it reports.
func TestFactoryRefuses(t *testing.T) {
	tests := []struct {
		name string

		// setup stubs the fixture's backend. Defaults to a valid single-
		// objective sweep when nil.
		setup func(*factoryFixture)

		wantErrIs       error
		wantErrContains string
	}{
		{
			name: "a server without local scheduler support",
			setup: func(f *factoryFixture) {
				f.localSchedulerEnabled = false
				// No sweep stub: the support check must fail before the fetch.
			},
			wantErrIs: scheduler.ErrUnsupportedServer,
		},
		{
			name:      "a sweep that does not exist",
			setup:     func(f *factoryFixture) { f.stubMissingSweep() },
			wantErrIs: scheduler.ErrSweepNotFound,
		},
		{
			// An unnamed objective would leave the loop searching against
			// fewer objectives than the sweep declares.
			name: "an unnamed multi-objective metric",
			setup: func(f *factoryFixture) {
				f.stubSweep("metrics:\n  - name: loss\n  - goal: minimize\n")
			},
			wantErrContains: "metrics[1] has no name",
		},
		{
			// Setting both would silently mask metric with metrics.
			name: "both metric and metrics",
			setup: func(f *factoryFixture) {
				f.stubSweep("metric:\n  name: loss\nmetrics:\n  - name: latency\n")
			},
			wantErrContains: "sets both metric and metrics",
		},
		{
			name:            "a sweep without an objective",
			setup:           func(f *factoryFixture) { f.stubSweep("method: bayes\n") },
			wantErrContains: "names no objective metric",
		},
		{
			name:            "a malformed sweep config",
			setup:           func(f *factoryFixture) { f.stubSweep("metric: [unterminated\n") },
			wantErrContains: "parsing sweep config",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newFactoryFixture()
			test.setup(fixture)

			_, _, err := fixture.startSession(t)

			if test.wantErrIs != nil {
				assert.ErrorIs(t, err, test.wantErrIs)
			}
			if test.wantErrContains != "" {
				assert.ErrorContains(t, err, test.wantErrContains)
			}
		})
	}
}
