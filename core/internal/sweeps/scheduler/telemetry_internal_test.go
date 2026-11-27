package scheduler

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/observability"
)

// newTelemetryScheduler returns a Scheduler whose logger exports to a
// test OTLP collector, plus the collector to read the events back from.
func newTelemetryScheduler(
	t *testing.T,
) (*Scheduler, *analyticstest.OpenTelemetryProxyTest) {
	t.Helper()

	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		analytics.NewTelemetryRecorder(
			proxy.OpenTelemetryProxy,
			analytics.NewTelemetryContext(),
		),
	)

	return NewScheduler(SchedulerParams{Logger: logger}), proxy
}

// event flushes the exporter's batch and returns the named event's
// counter and log record.
func event(
	t *testing.T,
	proxy *analyticstest.OpenTelemetryProxyTest,
	name string,
) (analyticstest.Metric, analyticstest.Log) {
	t.Helper()
	require.NoError(t, proxy.Shutdown(context.Background()))

	counter, ok := proxy.FindMetric(name)
	require.True(t, ok, "expected a counter for %q", name)
	log, ok := proxy.FindLog(name)
	require.True(t, ok, "expected an event for %q", name)
	return counter, log
}

func TestRecordFatalErrorCountsThePhaseAndError(t *testing.T) {
	scheduler, proxy := newTelemetryScheduler(t)

	scheduler.recordFatalError(phasePoll, "the backend said 403")

	counter, log := event(t, proxy, eventFatalError)
	assert.EqualValues(t, 1, counter.Value)
	assert.Equal(t, "poll", log.Attributes["phase"])
	// Keyed "error", not "message": a log record's body is already its
	// message, so a second one would be ambiguous to query.
	assert.Equal(t, "the backend said 403", log.Attributes["error"])
}

func TestRecordStepAbandonedCountsThePhaseAndError(t *testing.T) {
	scheduler, proxy := newTelemetryScheduler(t)

	scheduler.recordStepAbandoned(phaseWarmStart, errors.New("rate limited"))

	counter, log := event(t, proxy, eventStepAbandoned)
	assert.EqualValues(t, 1, counter.Value)
	assert.Equal(t, "warm_start", log.Attributes["phase"])
	assert.Equal(t, "rate limited", log.Attributes["error"])
}

func TestRecordRunDiscardedCountsTheCauseAndRun(t *testing.T) {
	scheduler, proxy := newTelemetryScheduler(t)

	scheduler.recordRunDiscarded(discardCauseBadConfig, "opt-1")

	counter, log := event(t, proxy, eventRunDiscarded)
	assert.EqualValues(t, 1, counter.Value)
	assert.Equal(t, "bad_config", log.Attributes["cause"])
	assert.Equal(t, "opt-1", log.Attributes["id"])
}

// Repeated failures of one kind add up, since the counter is what says
// whether a sweep is failing occasionally or constantly.
func TestRepeatedEventsAccumulateOnOneCounter(t *testing.T) {
	scheduler, proxy := newTelemetryScheduler(t)

	scheduler.recordRunDiscarded(discardCauseEnqueueFailed, "opt-1")
	scheduler.recordRunDiscarded(discardCauseEnqueueFailed, "opt-2")

	counter, _ := event(t, proxy, eventRunDiscarded)
	assert.EqualValues(t, 2, counter.Value)
}

// Every phase reaches telemetry under its config-facing name, so a
// rename cannot silently break the dashboards querying them.
func TestEveryPhaseIsRecordedUnderItsName(t *testing.T) {
	for _, phase := range []loopPhase{
		phaseWarmStart, phasePoll, phaseEnqueue, phaseOptimizer,
	} {
		t.Run(string(phase), func(t *testing.T) {
			scheduler, proxy := newTelemetryScheduler(t)

			scheduler.recordFatalError(phase, "failed")

			_, log := event(t, proxy, eventFatalError)
			assert.Equal(t, string(phase), log.Attributes["phase"])
		})
	}
}
