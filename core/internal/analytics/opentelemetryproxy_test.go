package analytics_test

import (
	"context"
	"runtime"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	otellogapi "go.opentelemetry.io/otel/log"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/version"
)

func TestTelemetryRecorder_RecordsDefaultAttributes(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	recorder.IncrementCounterAndLogEvent(
		t.Context(),
		"default_attrs_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	// Both logs and metrics carry the default low-cardinality attributes.
	log, ok := proxy.FindLog("default_attrs_event")
	require.True(t, ok, "expected a log for the event")
	metric, ok := proxy.FindMetric("default_attrs_event")
	require.True(t, ok, "expected a metric for the event")
	for _, attrs := range []map[string]string{log.Attributes, metric.Attributes} {
		assert.Equal(t, version.Version, attrs["wandb_version"])
		assert.Equal(t, runtime.Version(), attrs["go_version"])
		assert.Equal(t, runtime.GOOS, attrs["operating_system"])
	}
}

func TestTelemetryRecorder_With_LowCardinalityAttributes(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	derived := recorder.With(
		analytics.LowCardinalityAttributes{ErrorOriginator: "MyFunction"},
		nil,
	)
	derived.IncrementCounterAndLogEvent(
		t.Context(),
		"low_card_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	log, ok := proxy.FindLog("low_card_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "MyFunction", log.Attributes["error.originator"])

	metric, ok := proxy.FindMetric("low_card_event")
	require.True(t, ok, "expected a metric for the event")
	assert.Equal(t, "MyFunction", metric.Attributes["error.originator"])
}

func TestTelemetryRecorder_With_InheritsAndIgnoresEmptyFields(
	t *testing.T,
) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	// Chained derivation: each child inherits its parent's attributes,
	// and empty fields must not overwrite inherited or default values.
	derived := recorder.With(
		analytics.LowCardinalityAttributes{WandbVersion: "custom-version"},
		nil,
	)
	derived = derived.With(analytics.LowCardinalityAttributes{}, nil)
	derived = derived.With(
		analytics.LowCardinalityAttributes{ErrorOriginator: "MyFunction"},
		nil,
	)
	derived.Log(
		t.Context(),
		"empty_fields_event",
		nil,
		otellogapi.SeverityInfo,
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	log, ok := proxy.FindLog("empty_fields_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "custom-version", log.Attributes["wandb_version"])
	assert.Equal(t, runtime.Version(), log.Attributes["go_version"])
	assert.Equal(t, "MyFunction", log.Attributes["error.originator"])
}

func TestTelemetryRecorder_With_HighCardinalityLogsOnly(
	t *testing.T,
) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	derived := recorder.With(
		analytics.LowCardinalityAttributes{},
		map[string]string{"arbitrary_key": "value"},
	)
	derived.IncrementCounterAndLogEvent(
		t.Context(),
		"high_card_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	// High-cardinality attributes are attached to log records...
	log, ok := proxy.FindLog("high_card_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "value", log.Attributes["arbitrary_key"])

	// ...but never to metrics, where they would blow up cardinality.
	metric, ok := proxy.FindMetric("high_card_event")
	require.True(t, ok, "expected a metric for the event")
	assert.NotContains(t, metric.Attributes, "arbitrary_key")
}

func TestTelemetryRecorder_With_DoesNotAffectParent(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	recorder.With(
		analytics.LowCardinalityAttributes{ErrorOriginator: "ChildFunction"},
		map[string]string{"child_key": "child-value"},
	)
	recorder.IncrementCounterAndLogEvent(
		t.Context(),
		"parent_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	// Records emitted through the parent must not carry the
	// child's attributes.
	log, ok := proxy.FindLog("parent_event")
	require.True(t, ok, "expected a log for the parent event")
	assert.NotContains(t, log.Attributes, "child_key")
	assert.NotContains(t, log.Attributes, "error.originator")

	metric, ok := proxy.FindMetric("parent_event")
	require.True(t, ok, "expected a metric for the parent event")
	assert.NotContains(t, metric.Attributes, "error.originator")
}

func TestTelemetryRecorder_With_SharesShutdown(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	derived := recorder.With(analytics.LowCardinalityAttributes{}, nil)
	require.NoError(t, proxy.Shutdown(context.Background()))

	// After the root proxy shuts down, derived recorders are no-ops.
	derived.Log(
		t.Context(),
		"after_shutdown",
		nil,
		otellogapi.SeverityInfo,
	)

	_, ok := proxy.FindLog("after_shutdown")
	assert.False(t, ok, "expected no log from a derived recorder after shutdown")
}

func TestTelemetryRecorder_PerRecordAttributesOverrideContext(
	t *testing.T,
) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	derived := recorder.With(
		analytics.LowCardinalityAttributes{WandbVersion: "from-context"},
		map[string]string{"test_key": "from-context"},
	)
	derived.IncrementCounterAndLogEvent(
		t.Context(),
		"override_event",
		map[string]string{"test_key": "from-argument"},
		analytics.LowCardinalityAttributes{WandbVersion: "from-argument"},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	log, ok := proxy.FindLog("override_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "from-context", log.Attributes["wandb_version"])
	assert.Equal(t, "from-argument", log.Attributes["test_key"])

	metric, ok := proxy.FindMetric("override_event")
	require.True(t, ok, "expected a metric for the event")
	assert.Equal(t, "from-argument", metric.Attributes["wandb_version"])
}

func TestTelemetryRecorder_PerRecordAttributesDoNotPersist(
	t *testing.T,
) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	recorder.IncrementCounterAndLogEvent(
		t.Context(),
		"with_overrides",
		map[string]string{"test_key": "per-record"},
		analytics.LowCardinalityAttributes{WandbVersion: "per-record"},
	)
	recorder.Log(
		t.Context(),
		"without_overrides",
		nil,
		otellogapi.SeverityInfo,
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	// Per-record attributes must not leak into the telemetry context
	// and affect subsequent records.
	log, ok := proxy.FindLog("without_overrides")
	require.True(t, ok, "expected a log for the second record")
	assert.Equal(t, version.Version, log.Attributes["wandb_version"])
	assert.NotContains(t, log.Attributes, "test_key")
}

func TestTelemetryRecorder_RecordLog(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	recorder.Log(
		t.Context(),
		"hello world",
		map[string]string{"custom": "value"},
		otellogapi.SeverityInfo,
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	log, ok := proxy.FindLog("hello world")
	require.True(t, ok, "expected a log with the recorded body")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
	assert.Equal(t, version.Version, log.Attributes["wandb_version"])
}

func TestTelemetryRecorder_RecordMetricAndLogEvent(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	recorder.IncrementCounterAndLogEvent(
		t.Context(),
		"an_event",
		map[string]string{
			"custom": "value",
		},
		analytics.LowCardinalityAttributes{ErrorOriginator: "X"},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	// verify metric emitted
	metric, ok := proxy.FindMetric("an_event")
	require.True(t, ok, "expected a metric named after the event")
	assert.Equal(t, int64(1), metric.Value)
	assert.Equal(t, "X", metric.Attributes["error.originator"])

	// verify log emitted
	log, ok := proxy.FindLog("an_event")
	require.True(t, ok, "expected a log named after the event")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
}

func TestTelemetryRecorder_SendsAPIKeyAuth(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)

	recorder.IncrementCounterAndLogEvent(
		t.Context(),
		"authenticated_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	requests := proxy.Requests()
	require.NotEmpty(t, requests, "expected at least one OTLP export request")
	for _, req := range requests {
		assert.Equal(
			t,
			"Basic YXBpOnRlc3QtYXBpLWtleQ==",
			req.Authorization,
			"path %s",
			req.Path,
		)
	}
}

func TestTelemetryRecorder_Error(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)
	recorder = recorder.With(
		analytics.LowCardinalityAttributes{WandbVersion: "custom-version"},
		map[string]string{"request_id": "test-request"},
	)

	const wantErrorOriginator = "TestTelemetryRecorder_Error"
	recorder.Error(
		t.Context(),
		"error-message",
		assert.AnError,
		wantErrorOriginator,
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	metric, ok := proxy.FindMetric("error")
	require.True(t, ok, "expected an error metric")
	assert.Equal(t, int64(1), metric.Value)
	assert.Equal(
		t,
		wantErrorOriginator,
		metric.Attributes["error.originator"],
	)
	assert.Equal(t, "custom-version", metric.Attributes["wandb_version"])
	assert.NotContains(t, metric.Attributes, "request_id")

	// verify log emitted
	log, ok := proxy.FindLog("error-message")
	require.True(t, ok, "expected an error log")
	assert.Equal(t, otellogapi.SeverityError, log.Severity)
	assert.Equal(t, wantErrorOriginator, log.Attributes["error.originator"])
	assert.Equal(t, "custom-version", log.Attributes["wandb_version"])
	assert.Equal(t, "test-request", log.Attributes["request_id"])
	assert.Equal(t, assert.AnError.Error(), log.Attributes["error.message"])
	assert.NotEmpty(t, log.Attributes["error.stacktrace"])
}

func TestOpenTelemetryProxy_Shutdown_CalledMultipleTimes(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)

	require.NoError(t, proxy.Shutdown(context.Background()))

	// A second shutdown should not error.
	require.NoError(t, proxy.Shutdown(context.Background()))
}

func TestTelemetryRecorder_RecordAfterShutdown_IsNoop(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	recorder.Log(
		t.Context(),
		"after",
		nil,
		otellogapi.SeverityInfo,
	)

	_, ok := proxy.FindLog("after")
	assert.False(t, ok, "expected no log to be exported after shutdown")
}
