package analytics_test

import (
	"context"
	"fmt"
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

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/version"
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

func setProxyEnabledValueForTest(t *testing.T, v bool) {
	t.Helper()
	analytics.SetEnabled(v)
	t.Cleanup(func() { analytics.SetEnabled(true) })
}

// startProxy creates and starts a real proxy against the given endpoint,
// returning the concrete implementation for assertions on internal state.
func startProxy(
	t *testing.T,
	endpoint string,
	apiKey string,
) *analytics.OpenTelemetryProxyImpl {
	t.Helper()
	setProxyEnabledValueForTest(t, true)

	proxy := analytics.NewOpenTelemetryProxy(endpoint, apiKey)
	impl, ok := proxy.(*analytics.OpenTelemetryProxyImpl)
	require.True(
		t,
		ok,
		"expected *OpenTelemetryProxyImpl when analytics is enabled",
	)

	require.NoError(t, impl.Start(context.Background()))
	t.Cleanup(func() {
		require.NoError(t, impl.Shutdown(context.Background()))
	})
	return impl
}

func TestNewTelemetryContext_Defaults(t *testing.T) {
	tc := analytics.NewTelemetryContext()

	snapshot := tc.LowCardinalitySnapshot(nil)

	assert.Equal(t, version.Version, snapshot["wandb_version"])
	assert.Equal(t, runtime.Version(), snapshot["go_version"])
	assert.Equal(t, runtime.GOOS, snapshot["operating_system"])
}

func TestTelemetryContext_AddLowCardinalityAttributes(t *testing.T) {
	tc := analytics.NewTelemetryContext()
	tc.SetLowCardinalityAttributes(map[string]string{
		"exception.type": "MyError",
	})

	snapshot := tc.LowCardinalitySnapshot(nil)

	assert.Equal(t, "MyError", snapshot["exception.type"])
}

func TestTelemetryContext_AddLowCardinalityAttributes_DropsUnallowedKeys(
	t *testing.T,
) {
	tc := analytics.NewTelemetryContext()
	tc.SetLowCardinalityAttributes(map[string]string{
		"not_allowed_key": "should-be-dropped",
	})

	snapshot := tc.LowCardinalitySnapshot(nil)

	assert.NotContains(t, snapshot, "not_allowed_key")
}

func TestTelemetryContext_AddLowCardinalityAttributes_EmptyIsNoop(
	t *testing.T,
) {
	tc := analytics.NewTelemetryContext()
	before := tc.LowCardinalitySnapshot(nil)

	tc.SetLowCardinalityAttributes(nil)
	assert.Equal(t, before, tc.LowCardinalitySnapshot(nil))

	tc.SetLowCardinalityAttributes(map[string]string{})
	assert.Equal(t, before, tc.LowCardinalitySnapshot(nil))
}

func TestTelemetryContext_AddHighCardinalityAttributes_AcceptsAnyKey(
	t *testing.T,
) {
	tc := analytics.NewTelemetryContext()
	tc.AddHighCardinalityAttributes(map[string]string{
		"arbitrary_key": "value",
	})

	snapshot := tc.HighCardinalitySnapshot(nil)

	assert.Equal(t, "value", snapshot["arbitrary_key"])
}

func TestTelemetryContext_Snapshot_ArgumentOverridesContext(t *testing.T) {
	tc := analytics.NewTelemetryContext()
	tc.AddHighCardinalityAttributes(
		map[string]string{"test_key": "from-context"},
	)
	tc.SetLowCardinalityAttributes(
		map[string]string{"wandb_version": "from-context"},
	)

	highCardinalitySnapshot := tc.HighCardinalitySnapshot(
		map[string]string{"test_key": "from-argument"},
	)
	lowCardinalitySnapshot := tc.LowCardinalitySnapshot(
		map[string]string{"wandb_version": "from-argument"},
	)

	assert.Equal(t, "from-argument", highCardinalitySnapshot["test_key"])
	assert.Equal(t, "from-argument", lowCardinalitySnapshot["wandb_version"])
}

func TestTelemetryContext_SnapshotsDoesNotUpdateInternalState(t *testing.T) {
	tc := analytics.NewTelemetryContext()
	snapshot := tc.LowCardinalitySnapshot(nil)

	snapshot["go_version"] = "mutated"

	// Mutating the returned snapshot must not affect the context.
	assert.Equal(
		t,
		runtime.Version(),
		tc.LowCardinalitySnapshot(nil)["go_version"],
	)
}

func TestNewOpenTelemetryProxy_NoAPIKey_ReturnsNoopProxy(t *testing.T) {
	setProxyEnabledValueForTest(t, true)
	proxy := analytics.NewOpenTelemetryProxy("http://example.invalid", "")

	_, ok := proxy.(analytics.NoopOpenTelemetryProxy)

	assert.True(t, ok, "expected NoopOpenTelemetryProxy when API key is empty")
}

func TestNewOpenTelemetryProxy_WithAPIKey_ReturnsImpl(t *testing.T) {
	setProxyEnabledValueForTest(t, true)
	proxy := analytics.NewOpenTelemetryProxy("http://example.invalid", "test-api-key")

	_, ok := proxy.(*analytics.OpenTelemetryProxyImpl)

	assert.True(t, ok, "expected *OpenTelemetryProxyImpl when proxy is enabled")
}

func TestOpenTelemetryProxyImpl_RecordLog(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.RecordLog(
		t.Context(),
		"hello world",
		map[string]string{"custom": "value"},
		otellogapi.SeverityInfo,
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	log, ok := findLog(captured.logs, "hello world")
	require.True(t, ok, "expected a log with the recorded body")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
	assert.Equal(t, version.Version, log.Attributes["wandb_version"])
}

func TestOpenTelemetryProxyImpl_RecordMetricAndLogEvent(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.RecordMetricAndLogEvent(t.Context(), "an_event", map[string]string{
		"exception.type": "X",
		"custom":         "value",
	})
	require.NoError(t, impl.Shutdown(context.Background()))

	// verify metric emitted
	metric, ok := findMetric(captured.metrics, "an_event")
	require.True(t, ok, "expected a metric named after the event")
	assert.Equal(t, int64(1), metric.Value)
	assert.Equal(t, "X", metric.Attributes["exception.type"])

	// verify log emitted
	log, ok := findLog(captured.logs, "an_event")
	require.True(t, ok, "expected a log named after the event")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
}

func TestOpenTelemetryProxyImpl_SendsAPIKeyAuth(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.RecordMetricAndLogEvent(t.Context(), "authenticated_event", nil)
	require.NoError(t, impl.Shutdown(context.Background()))

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

func TestOpenTelemetryProxyImpl_Exception(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.Exception(t.Context(), "error-message", assert.AnError)
	require.NoError(t, impl.Shutdown(context.Background()))

	// verify metric emitted
	metric, ok := findMetric(captured.metrics, "exception")
	require.True(t, ok, "expected an exception metric")
	assert.Equal(t, int64(1), metric.Value)
	assert.NotEmpty(t, metric.Attributes["exception.type"])

	// verify log emitted
	log, ok := findLog(captured.logs, "error-message")
	require.True(t, ok, "expected an exception log")
	assert.Equal(t, otellogapi.SeverityError, log.Severity)
	assert.Equal(t,
		fmt.Sprintf("%T", assert.AnError),
		log.Attributes["exception.type"],
	)
	assert.Equal(t, assert.AnError.Error(), log.Attributes["exception.message"])
	assert.NotEmpty(t, log.Attributes["exception.stacktrace"])
}

func TestOpenTelemetryProxyImpl_Shutdown_CalledMultipleTimes(t *testing.T) {
	url, _ := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	require.NoError(t, impl.Shutdown(context.Background()))

	// A second shutdown should not error.
	require.NoError(t, impl.Shutdown(context.Background()))
}

func TestOpenTelemetryProxyImpl_RecordAfterShutdown_IsNoop(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")
	require.NoError(t, impl.Shutdown(context.Background()))

	impl.RecordLog(t.Context(), "after", nil, otellogapi.SeverityInfo)

	_, ok := findLog(captured.logs, "after")
	assert.False(t, ok, "expected no log to be exported after shutdown")
}

func TestNoopOpenTelemetryProxy_AllMethodsAreSafe(t *testing.T) {
	var proxy analytics.OpenTelemetryProxy = analytics.NoopOpenTelemetryProxy{}

	require.NoError(t, proxy.Start(context.Background()))
	assert.NotPanics(t, func() {
		proxy.RecordLog(
			t.Context(),
			"body",
			map[string]string{"k": "v"},
			otellogapi.SeverityInfo,
		)
		proxy.RecordMetricAndLogEvent(
			t.Context(),
			"event",
			map[string]string{"k": "v"},
		)
		proxy.Exception(context.Background(), "message", assert.AnError)
	})
	require.NoError(t, proxy.Shutdown(context.Background()))
}
