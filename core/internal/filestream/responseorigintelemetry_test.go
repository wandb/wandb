package filestream

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/observability"
)

var allUnmarked404Events = []string{
	eventUnmarked404Recovered,
	eventUnmarked404DeadlineExceeded,
	eventUnmarked404StoppedByServer,
}

// newTelemetryLogger returns a logger that exports telemetry to a test
// OTLP collector, plus the collector to read the events back from.
func newTelemetryLogger(
	t *testing.T,
) (*observability.CoreLogger, *analyticstest.OpenTelemetryProxyTest) {
	t.Helper()

	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		analytics.NewTelemetryRecorder(
			proxy.OpenTelemetryProxy,
			analytics.NewTelemetryContext(),
		),
	)
	return logger, proxy
}

// recordedEvents flushes the exporter and returns the counter value and
// log record of each named event that was recorded.
func recordedEvents(
	t *testing.T,
	proxy *analyticstest.OpenTelemetryProxyTest,
) (map[string]int64, map[string]analyticstest.Log) {
	t.Helper()
	require.NoError(t, proxy.Shutdown(context.Background()))

	counts := make(map[string]int64)
	logs := make(map[string]analyticstest.Log)
	for _, name := range allUnmarked404Events {
		if counter, ok := proxy.FindMetric(name); ok {
			counts[name] = counter.Value
		}
		if log, ok := proxy.FindLog(name); ok {
			logs[name] = log
		}
	}
	return counts, logs
}

// policyWithTelemetry returns a request context with the header-less 404
// rule and a telemetry-exporting logger.
//
// Calling finish records the deferred telemetry, like the filestream does
// when it finishes.
func policyWithTelemetry(
	t *testing.T,
	deadline time.Duration,
) (
	ctx context.Context,
	proxy *analyticstest.OpenTelemetryProxyTest,
	finish func(),
) {
	t.Helper()
	logger, proxy := newTelemetryLogger(t)
	deferred := &deferredTelemetry{}
	ctx = withUnmarked404Retry(t.Context(), deadline, logger, deferred)
	return ctx, proxy, func() { deferred.flush(logger) }
}

func TestTelemetry_RetryThenSuccess_RecordsRecovery(t *testing.T) {
	ctx, proxy, _ := policyWithTelemetry(t, time.Hour)

	for range 3 {
		_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	}
	_, _ = RetryPolicy(ctx, response(http.StatusOK, true), nil)

	counts, logs := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404Recovered: 1,
	}, counts)
	assert.Equal(t, "3", logs[eventUnmarked404Recovered].Attributes["unmarked_404s"])
	assert.Equal(t, "0", logs[eventUnmarked404Recovered].Attributes["duration_seconds"])
	assert.Equal(t, "3600", logs[eventUnmarked404Recovered].Attributes["deadline_seconds"])
}

// While header-less 404s keep arriving, the server is likely unreachable and
// telemetry sent then would be dropped, so nothing is recorded yet, not even
// when the deadline runs out.
func TestTelemetry_DuringOutage_RecordsNothing(t *testing.T) {
	ctx, proxy, _ := policyWithTelemetry(t, time.Nanosecond)

	first, _ := RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	time.Sleep(time.Millisecond)
	second, _ := RetryPolicy(ctx, response(http.StatusNotFound, false), nil)

	counts, _ := recordedEvents(t, proxy)
	assert.True(t, first)
	assert.False(t, second)
	assert.Empty(t, counts)
}

func TestTelemetry_PastDeadline_RecordsDeadlineExceededAtFinish(t *testing.T) {
	ctx, proxy, finish := policyWithTelemetry(t, time.Nanosecond)

	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	time.Sleep(time.Millisecond)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	finish()

	counts, logs := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404DeadlineExceeded: 1,
	}, counts)
	assert.Equal(t, "2", logs[eventUnmarked404DeadlineExceeded].Attributes["unmarked_404s"])
}

// Each new run of header-less 404s logs a warning, so the local log shows
// when the deadline restarted.
func TestLogs_RestartedStreak_LogsWarningAgain(t *testing.T) {
	var logs bytes.Buffer
	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(&logs, nil)),
		analytics.NewTelemetryRecorder(nil, analytics.NewTelemetryContext()),
	)
	ctx := withUnmarked404Retry(t.Context(), time.Hour, logger, &deferredTelemetry{})

	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusServiceUnavailable, true), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)

	assert.Equal(t, 1, strings.Count(logs.String(), "likely from a load balancer or proxy; retrying"))
	assert.Equal(t, 1, strings.Count(logs.String(), "resumed after a different response"))
}

func TestTelemetry_MarkedNotFound_RecordsStoppedByServer(t *testing.T) {
	ctx, proxy, _ := policyWithTelemetry(t, time.Hour)

	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, true), nil)

	counts, logs := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404StoppedByServer: 1,
	}, counts)
	assert.Equal(t, "1", logs[eventUnmarked404StoppedByServer].Attributes["unmarked_404s"])
}

// A 503 or connection error in between restarts the deadline, but the
// request is still one request: one outcome, counting all of its
// header-less 404s.
func TestTelemetry_OtherFailuresInBetween_OneOutcome(t *testing.T) {
	ctx, proxy, _ := policyWithTelemetry(t, time.Hour)

	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusServiceUnavailable, true), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, nil, io.ErrUnexpectedEOF)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusOK, true), nil)

	counts, logs := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404Recovered: 1,
	}, counts)
	assert.Equal(t, "3", logs[eventUnmarked404Recovered].Attributes["unmarked_404s"])
}

// Without the rule, nothing is recorded, even for header-less 404s.
func TestTelemetry_WithoutRule_RecordsNothing(t *testing.T) {
	logger, proxy := newTelemetryLogger(t)
	_ = logger // the rule is off, so the policy has no logger to use

	_, _ = RetryPolicy(t.Context(), response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(t.Context(), response(http.StatusOK, true), nil)

	counts, _ := recordedEvents(t, proxy)
	assert.Empty(t, counts)
}

// End to end through the real retry client: one request that gets three
// header-less 404s and then succeeds records one recovery.
func TestTelemetry_EndToEnd_RecordsRecovery(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	logger, proxy := newTelemetryLogger(t)
	opts := defaultOriginOptions()
	opts.logger = logger
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, opts)

	s.then(unmarkedNotFound, unmarkedNotFound, unmarkedNotFound)
	logStep(fs, 1)
	fs.FinishWithoutExit()

	counts, logs := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404Recovered: 1,
	}, counts)
	assert.Equal(t, "3", logs[eventUnmarked404Recovered].Attributes["unmarked_404s"])
}

// A 503 between the header-less 404s and the success restarts the deadline,
// but the request still needed the 404 retries, so its recovery counts.
func TestTelemetry_ServerErrorBeforeSuccess_StillRecordsRecovery(t *testing.T) {
	ctx, proxy, _ := policyWithTelemetry(t, time.Hour)

	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusServiceUnavailable, true), nil)
	_, _ = RetryPolicy(ctx, response(http.StatusOK, true), nil)

	counts, logs := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404Recovered: 1,
	}, counts)
	assert.Equal(t, "1", logs[eventUnmarked404Recovered].Attributes["unmarked_404s"])
}

// Same for a server 404 that ends the request after a 503.
func TestTelemetry_ServerErrorBeforeMarkedNotFound_StillRecordsStop(t *testing.T) {
	ctx, proxy, _ := policyWithTelemetry(t, time.Hour)

	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, false), nil)
	_, _ = RetryPolicy(ctx, nil, io.ErrUnexpectedEOF)
	_, _ = RetryPolicy(ctx, response(http.StatusNotFound, true), nil)

	counts, _ := recordedEvents(t, proxy)
	assert.Equal(t, map[string]int64{
		eventUnmarked404StoppedByServer: 1,
	}, counts)
}

// End to end: header-less 404s, a 503, then success records one recovery,
// and every row arrives.
func TestTelemetry_EndToEnd_ServerErrorBeforeSuccess(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	logger, proxy := newTelemetryLogger(t)
	opts := defaultOriginOptions()
	opts.logger = logger
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, opts)

	s.then(
		unmarkedNotFound,
		unmarkedNotFound,
		scriptedResponse{http.StatusServiceUnavailable, true},
	)
	logStep(fs, 1)
	fs.FinishWithoutExit()

	counts, logs := recordedEvents(t, proxy)
	assert.ElementsMatch(t, []int64{0, 1}, s.acceptedSteps())
	assert.Equal(t, map[string]int64{
		eventUnmarked404Recovered: 1,
	}, counts)
	assert.Equal(t, "2", logs[eventUnmarked404Recovered].Attributes["unmarked_404s"])
}

// End to end: header-less 404s past the deadline stop uploads, and the
// deadline event waits until the filestream finishes.
func TestTelemetry_EndToEnd_DeadlineRecordedAtFinish(t *testing.T) {
	s := newOriginTestServer(t, unmarkedNotFound)
	logger, proxy := newTelemetryLogger(t)
	opts := defaultOriginOptions()
	opts.deadline = 100 * time.Millisecond
	opts.logger = logger
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, opts)

	logStep(fs, 1)
	requireDead(t, fs)
	fs.deferredTelemetry.mu.Lock()
	pendingBeforeFinish := len(fs.deferredTelemetry.events)
	fs.deferredTelemetry.mu.Unlock()
	fs.FinishWithoutExit()

	counts, _ := recordedEvents(t, proxy)
	assert.Equal(t, 1, pendingBeforeFinish)
	assert.Equal(t, map[string]int64{
		eventUnmarked404DeadlineExceeded: 1,
	}, counts)
}
