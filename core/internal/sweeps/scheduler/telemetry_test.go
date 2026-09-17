package scheduler_test

import (
	"context"
	"io"
	"log/slog"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sweeps/scheduler"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// telemetryFixture is a loopFixture whose logger exports to a test OTLP
// collector.
type telemetryFixture struct {
	*loopFixture
	proxy *analyticstest.OpenTelemetryProxyTest
}

func newTelemetryFixture(
	t *testing.T,
	params scheduler.SchedulerParams,
) *telemetryFixture {
	t.Helper()

	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	params.Logger = observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		analytics.NewTelemetryRecorder(
			proxy.OpenTelemetryProxy,
			analytics.NewTelemetryContext(),
		),
	)

	return &telemetryFixture{
		loopFixture: newLoopFixture(t, params),
		proxy:       proxy,
	}
}

// metric flushes the exporter's batch and returns one counter.
func (f *telemetryFixture) metric(
	t *testing.T,
	name string,
) (analyticstest.Metric, bool) {
	t.Helper()
	require.NoError(t, f.proxy.Shutdown(context.Background()))
	return f.proxy.FindMetric(name)
}

func TestRateLimitedWarmStartPageCountsAnAbandonedStep(t *testing.T) {
	fixture := newTelemetryFixture(t, scheduler.SchedulerParams{})

	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepRunsWithHistory"),
		&graphql.HTTPError{StatusCode: 429},
	)
	task := fixture.step(t, nil)
	require.True(t, task.GetWarmStart().HasMore)

	counter, ok := fixture.metric(t, "sweep_scheduler_step_abandoned")
	require.True(t, ok, "expected an abandoned-step counter")
	assert.EqualValues(t, 1, counter.Value)

	event, ok := fixture.proxy.FindLog("sweep_scheduler_step_abandoned")
	require.True(t, ok, "expected an abandoned-step event")
	assert.Equal(t, "warm_start", event.Attributes["phase"])
}

func TestFatalPollErrorIsCounted(t *testing.T) {
	fixture := newTelemetryFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepConfig"),
		&graphql.HTTPError{StatusCode: 403},
	)
	require.NotNil(t, fixture.step(t, warmResult(nil)).GetDone())

	counter, ok := fixture.metric(t, "sweep_scheduler_fatal_error")
	require.True(t, ok, "expected a fatal-error counter")
	assert.EqualValues(t, 1, counter.Value)

	event, ok := fixture.proxy.FindLog("sweep_scheduler_fatal_error")
	require.True(t, ok, "expected a fatal-error event")
	assert.Equal(t, "poll", event.Attributes["phase"])
}

func TestRateLimitedPollCountsAnAbandonedStep(t *testing.T) {
	fixture := newTelemetryFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)
	fixture.stubIdlePoll("RUNNING")
	fixture.step(t, warmResult(nil))

	fixture.client.StubMatchWithError(
		gqlmock.WithOpName("SweepConfig"),
		&graphql.HTTPError{StatusCode: 429},
	)
	require.NotNil(t, fixture.step(t, emptyIterResult()).GetGeneration())

	counter, ok := fixture.metric(t, "sweep_scheduler_step_abandoned")
	require.True(t, ok, "expected an abandoned-step counter")
	assert.EqualValues(t, 1, counter.Value)

	event, ok := fixture.proxy.FindLog("sweep_scheduler_step_abandoned")
	require.True(t, ok, "expected an abandoned-step event")
	assert.Equal(t, "poll", event.Attributes["phase"])
}

// The fatal-error metric is an internal signal about this scheduler,
// so counting one must not change what the sweep or the client sees:
// the client is told OPTIMIZER_ERROR, which names whose fault it was,
// and the sweep itself is left alone.
func TestOptimizerErrorIsCountedAsFatal(t *testing.T) {
	fixture := newTelemetryFixture(t, scheduler.SchedulerParams{})
	fixture.warmTo(t)

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
		done.GetDone().Reason,
		"an internal fatal count must not become a FATAL_ERROR reason")
	assert.Empty(t, fixture.requestsFor("UpsertSweepState"),
		"counting a fatal error must not transition the sweep")

	counter, ok := fixture.metric(t, "sweep_scheduler_fatal_error")
	require.True(t, ok, "expected a fatal-error counter")
	assert.EqualValues(t, 1, counter.Value)

	event, ok := fixture.proxy.FindLog("sweep_scheduler_fatal_error")
	require.True(t, ok, "expected a fatal-error event")
	assert.Equal(t, "optimizer", event.Attributes["phase"])
}
