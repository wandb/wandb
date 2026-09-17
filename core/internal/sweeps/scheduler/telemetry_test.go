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
