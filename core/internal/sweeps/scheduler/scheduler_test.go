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
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sweeps/schedulertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

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

// pollJSON builds a SweepWatchedRuns response: the sweep's state and
// one page of the runs the scheduler asked for by name.
func pollJSON(sweepState string, hasNext bool, cursor string, runs ...testRun) string {
	return encodeJSON(map[string]any{
		"project": map[string]any{
			"sweep": map[string]any{"state": sweepState},
			"runs":  runConnection(hasNext, cursor, runs),
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

// stubPoll answers one generation poll of the watched runs.
func (f *loopFixture) stubPoll(response string) {
	f.client.StubMatchOnce(gqlmock.WithOpName("SweepWatchedRuns"), response)
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
//
// Red until Step is implemented: it no longer asserts a warm-start task
// came back, since the stub Step returns a fixed Done task regardless of
// input. Once Step is implemented, restore the
// require.NotNil(t, task.GetWarmStart(), ...) assertion this replaced.
func (f *loopFixture) warmTo(t *testing.T) {
	t.Helper()
	f.stubWarmStart(warmJSON("RUNNING", false, ""))
	f.step(t, nil)
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

// assertUnimplemented asserts that task is the fixed Done task the
// stub Scheduler.Step returns.
//
// Red until Step is implemented: this is the standing assertion every
// test below ends with. As each behavior is implemented, replace the
// call to this helper with the real assertions it stands in for.
func assertUnimplemented(
	t *testing.T,
	task *spb.SweepSchedulerServerNextTaskResponse,
) {
	t.Helper()
	require.NotNil(t, task.GetDone())
	assert.Equal(t,
		spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
		task.GetDone().Reason)
}

func TestDeclinedAskAsksAgain(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.stubIdlePoll("RUNNING")
	first := fixture.step(t, warmResult(nil))
	assertUnimplemented(t, first)

	fixture.stubIdlePoll("RUNNING")
	second := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			AskOutcome: spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_DECLINED,
		}))
	assertUnimplemented(t, second)
}

func TestTerminateFinishesSweep(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	fixture.stubFinishSweep()
	done := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{Terminate: true}))

	assertUnimplemented(t, done)
}

func TestOptimizerErrorEndsLoopWithoutFinishingSweep(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
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

	assertUnimplemented(t, done)
}

func TestStopDuringPollExitsWithoutAsking(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	fixture.client.StubMatchHang(gqlmock.WithOpName("SweepConfig"))

	done := make(chan *spb.SweepSchedulerServerNextTaskResponse, 1)
	go func() {
		done <- fixture.scheduler.Step(context.Background(), emptyIterResult())
	}()

	fixture.scheduler.Stop()

	task := schedulertest.Receive(t, done)
	assertUnimplemented(t, task)
}

func TestSessionCancelReturnsShutdown(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	fixture.stubWarmStart(warmJSON("RUNNING", false, ""))
	task := fixture.scheduler.Step(ctx, nil)

	assertUnimplemented(t, task)
}

func TestTellErrorPopsRunAndContinues(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 2})
	fixture.warmTo(t)
	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "poison", state: "running"},
	))
	fixture.step(t, warmResult(map[string]string{"poison": "opt-p"}))

	fixture.stubIdlePoll("RUNNING")
	task := fixture.step(t, generationResult(
		&spb.SweepSchedulerClientGenerationResult{
			TellErrors: []*spb.SweepSchedulerClientTellError{
				{OptimizerRunId: "opt-p", Message: "bad summary"},
			},
		}))

	assertUnimplemented(t, task)
}

func TestDuplicateAdoptionDroppedWithoutDiscarding(t *testing.T) {
	fixture := newLoopFixture(t, scheduler.SchedulerParams{BatchSize: 3})
	fixture.stubWarmStart(warmJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
		testRun{name: "run-2", state: "running"},
	))
	fixture.step(t, nil)

	fixture.stubPoll(pollJSON("RUNNING", false, "",
		testRun{name: "run-1", state: "running"},
		testRun{name: "run-2", state: "running"},
	))
	task := fixture.step(t, warmResult(map[string]string{
		"run-1": "opt-dup",
		"run-2": "opt-dup",
	}))

	assertUnimplemented(t, task)
}
