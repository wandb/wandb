package analytics_test

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"runtime"
	"sync"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	otellogapi "go.opentelemetry.io/otel/log"
	collogspb "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	colmetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/analytics"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// capturedLog is a decoded OTLP log record received by the test server.
type capturedLog struct {
	Body       string
	Severity   otellogapi.Severity
	Attributes map[string]string
}

// capturedMetric is a decoded OTLP metric data point received by the test server.
type capturedMetric struct {
	Name       string
	Value      int64
	Attributes map[string]string
}

type capturedRequest struct {
	Path          string
	Authorization string
	Headers       http.Header
	URLHost       string
}

// capturedExports accumulates the telemetry decoded from OTLP/HTTP exports.
type capturedExports struct {
	mu       sync.Mutex
	logs     []capturedLog
	metrics  []capturedMetric
	requests []capturedRequest
}

func (c *capturedExports) addLogs(t *testing.T, body []byte) {
	t.Helper()
	var req collogspb.ExportLogsServiceRequest
	require.NoError(t, proto.Unmarshal(body, &req))

	c.mu.Lock()
	defer c.mu.Unlock()
	for _, rl := range req.GetResourceLogs() {
		for _, sl := range rl.GetScopeLogs() {
			for _, lr := range sl.GetLogRecords() {
				c.logs = append(c.logs, capturedLog{
					Body:       lr.GetBody().GetStringValue(),
					Severity:   otellogapi.Severity(lr.GetSeverityNumber()),
					Attributes: keyValuesToMap(lr.GetAttributes()),
				})
			}
		}
	}
}

func (c *capturedExports) addMetrics(t *testing.T, body []byte) {
	t.Helper()
	var req colmetricspb.ExportMetricsServiceRequest
	require.NoError(t, proto.Unmarshal(body, &req))

	c.mu.Lock()
	defer c.mu.Unlock()
	for _, rm := range req.GetResourceMetrics() {
		for _, sm := range rm.GetScopeMetrics() {
			for _, m := range sm.GetMetrics() {
				for _, dp := range m.GetSum().GetDataPoints() {
					c.metrics = append(c.metrics, capturedMetric{
						Name:       m.GetName(),
						Value:      dp.GetAsInt(),
						Attributes: keyValuesToMap(dp.GetAttributes()),
					})
				}
			}
		}
	}
}

func (c *capturedExports) addRequest(r *http.Request) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.requests = append(c.requests, capturedRequest{
		Path:          r.URL.Path,
		Authorization: r.Header.Get("Authorization"),
		Headers:       r.Header.Clone(),
		URLHost:       r.URL.Host,
	})
}

func (c *capturedExports) requestsSnapshot() []capturedRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]capturedRequest(nil), c.requests...)
}

// keyValuesToMap flattens OTLP string attributes into a plain map.
func keyValuesToMap(kvs []*commonpb.KeyValue) map[string]string {
	out := make(map[string]string, len(kvs))
	for _, kv := range kvs {
		out[kv.GetKey()] = kv.GetValue().GetStringValue()
	}
	return out
}

// findLog returns the first captured log whose body matches the provided value.
func findLog(logs []capturedLog, body string) (capturedLog, bool) {
	for _, l := range logs {
		if l.Body == body {
			return l, true
		}
	}
	return capturedLog{}, false
}

// findMetric returns the first captured metric data point with the given name.
func findMetric(metrics []capturedMetric, name string) (capturedMetric, bool) {
	for _, m := range metrics {
		if m.Name == name {
			return m, true
		}
	}
	return capturedMetric{}, false
}

// newOTLPTestServer starts an HTTP server that accepts OTLP/HTTP exports,
// decodes the protobuf payloads, and accumulates the telemetry it receives. It
// returns the server's base URL and the accumulator for assertions.
func newOTLPTestServer(t *testing.T) (baseURL string, captured *capturedExports) {
	t.Helper()

	captured = &capturedExports{}

	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			captured.addRequest(r)
			body, err := io.ReadAll(r.Body)
			if err != nil {
				t.Errorf("read export body: %v", err)
				w.WriteHeader(http.StatusInternalServerError)
				return
			}

			switch r.URL.Path {
			case "/sdk/otel/v1/logs":
				captured.addLogs(t, body)
			case "/sdk/otel/v1/metrics":
				captured.addMetrics(t, body)
			default:
				t.Errorf("unexpected export path: %s", r.URL.Path)
			}

			// An empty 200 response is treated as a successful export.
			w.WriteHeader(http.StatusOK)
		},
	))
	t.Cleanup(srv.Close)

	return srv.URL, captured
}

func newTestSettings(
	endpoint string,
	apiKey string,
	configure ...func(*spb.Settings),
) *wbsettings.Settings {
	settingsProto := &spb.Settings{
		BaseUrl: wrapperspb.String(endpoint),
		ApiKey:  wrapperspb.String(apiKey),
	}
	for _, configure := range configure {
		configure(settingsProto)
	}
	return wbsettings.From(settingsProto)
}

// startProxy creates a real proxy against the given endpoint.
func startProxy(
	t *testing.T,
	endpoint string,
	apiKey string,
) *analytics.OpenTelemetryProxy {
	t.Helper()

	return startProxyWithSettings(t, newTestSettings(endpoint, apiKey))
}

func startProxyWithSettings(
	t *testing.T,
	settings *wbsettings.Settings,
) *analytics.OpenTelemetryProxy {
	t.Helper()

	proxy := analytics.NewOpenTelemetryProxy(t.Context(), settings)
	require.NotNil(t, proxy)

	t.Cleanup(func() {
		require.NoError(t, proxy.Shutdown(context.Background()))
	})
	return proxy
}

func TestTelemetryRecorder_RecordsDefaultAttributes(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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
	log, ok := findLog(captured.logs, "default_attrs_event")
	require.True(t, ok, "expected a log for the event")
	metric, ok := findMetric(captured.metrics, "default_attrs_event")
	require.True(t, ok, "expected a metric for the event")
	for _, attrs := range []map[string]string{log.Attributes, metric.Attributes} {
		assert.Equal(t, version.Version, attrs["wandb_version"])
		assert.Equal(t, runtime.Version(), attrs["go_version"])
		assert.Equal(t, runtime.GOOS, attrs["operating_system"])
	}
}

func TestTelemetryRecorder_With_LowCardinalityAttributes(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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

	log, ok := findLog(captured.logs, "low_card_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "MyFunction", log.Attributes["error.originator"])

	metric, ok := findMetric(captured.metrics, "low_card_event")
	require.True(t, ok, "expected a metric for the event")
	assert.Equal(t, "MyFunction", metric.Attributes["error.originator"])
}

func TestTelemetryRecorder_With_InheritsAndIgnoresEmptyFields(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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

	log, ok := findLog(captured.logs, "empty_fields_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "custom-version", log.Attributes["wandb_version"])
	assert.Equal(t, runtime.Version(), log.Attributes["go_version"])
	assert.Equal(t, "MyFunction", log.Attributes["error.originator"])
}

func TestTelemetryRecorder_With_HighCardinalityLogsOnly(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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
	log, ok := findLog(captured.logs, "high_card_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "value", log.Attributes["arbitrary_key"])

	// ...but never to metrics, where they would blow up cardinality.
	metric, ok := findMetric(captured.metrics, "high_card_event")
	require.True(t, ok, "expected a metric for the event")
	assert.NotContains(t, metric.Attributes, "arbitrary_key")
}

func TestTelemetryRecorder_With_DoesNotAffectParent(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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
	log, ok := findLog(captured.logs, "parent_event")
	require.True(t, ok, "expected a log for the parent event")
	assert.NotContains(t, log.Attributes, "child_key")
	assert.NotContains(t, log.Attributes, "error.originator")

	metric, ok := findMetric(captured.metrics, "parent_event")
	require.True(t, ok, "expected a metric for the parent event")
	assert.NotContains(t, metric.Attributes, "error.originator")
}

func TestTelemetryRecorder_With_SharesShutdown(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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

	_, ok := findLog(captured.logs, "after_shutdown")
	assert.False(t, ok, "expected no log from a derived recorder after shutdown")
}

func TestTelemetryRecorder_PerRecordAttributesOverrideContext(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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

	log, ok := findLog(captured.logs, "override_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "from-context", log.Attributes["wandb_version"])
	assert.Equal(t, "from-argument", log.Attributes["test_key"])

	metric, ok := findMetric(captured.metrics, "override_event")
	require.True(t, ok, "expected a metric for the event")
	assert.Equal(t, "from-argument", metric.Attributes["wandb_version"])
}

func TestTelemetryRecorder_PerRecordAttributesDoNotPersist(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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
	log, ok := findLog(captured.logs, "without_overrides")
	require.True(t, ok, "expected a log for the second record")
	assert.Equal(t, version.Version, log.Attributes["wandb_version"])
	assert.NotContains(t, log.Attributes, "test_key")
}

func TestTelemetryRecorder_RecordLog(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
		analytics.NewTelemetryContext(),
	)

	recorder.Log(
		t.Context(),
		"hello world",
		map[string]string{"custom": "value"},
		otellogapi.SeverityInfo,
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	log, ok := findLog(captured.logs, "hello world")
	require.True(t, ok, "expected a log with the recorded body")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
	assert.Equal(t, version.Version, log.Attributes["wandb_version"])
}

func TestTelemetryRecorder_RecordMetricAndLogEvent(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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
	metric, ok := findMetric(captured.metrics, "an_event")
	require.True(t, ok, "expected a metric named after the event")
	assert.Equal(t, int64(1), metric.Value)
	assert.Equal(t, "X", metric.Attributes["error.originator"])

	// verify log emitted
	log, ok := findLog(captured.logs, "an_event")
	require.True(t, ok, "expected a log named after the event")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
}

func TestTelemetryRecorder_SendsAPIKeyAuth(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
		analytics.NewTelemetryContext(),
	)

	recorder.IncrementCounterAndLogEvent(
		t.Context(),
		"authenticated_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	requests := captured.requestsSnapshot()
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
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
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

	metric, ok := findMetric(captured.metrics, "error")
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
	log, ok := findLog(captured.logs, "error-message")
	require.True(t, ok, "expected an error log")
	assert.Equal(t, otellogapi.SeverityError, log.Severity)
	assert.Equal(t, wantErrorOriginator, log.Attributes["error.originator"])
	assert.Equal(t, "custom-version", log.Attributes["wandb_version"])
	assert.Equal(t, "test-request", log.Attributes["request_id"])
	assert.Equal(t, assert.AnError.Error(), log.Attributes["error.message"])
	assert.NotEmpty(t, log.Attributes["error.stacktrace"])
}

func TestOpenTelemetryProxy_Shutdown_CalledMultipleTimes(t *testing.T) {
	url, _ := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")

	require.NoError(t, proxy.Shutdown(context.Background()))

	// A second shutdown should not error.
	require.NoError(t, proxy.Shutdown(context.Background()))
}

func TestTelemetryRecorder_RecordAfterShutdown_IsNoop(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	proxy := startProxy(t, url, "test-api-key")
	recorder := analytics.NewTelemetryRecorder(
		proxy,
		analytics.NewTelemetryContext(),
	)
	require.NoError(t, proxy.Shutdown(context.Background()))

	recorder.Log(
		t.Context(),
		"after",
		nil,
		otellogapi.SeverityInfo,
	)

	_, ok := findLog(captured.logs, "after")
	assert.False(t, ok, "expected no log to be exported after shutdown")
}
