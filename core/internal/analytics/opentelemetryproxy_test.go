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

// startProxy creates and starts a real proxy against the given endpoint,
// returning the concrete implementation for assertions on internal state.
func startProxy(
	t *testing.T,
	endpoint string,
	apiKey string,
) *analytics.OpenTelemetryProxyImpl {
	t.Helper()

	return startProxyWithSettings(t, newTestSettings(endpoint, apiKey))
}

func startProxyWithSettings(
	t *testing.T,
	settings *wbsettings.Settings,
) *analytics.OpenTelemetryProxyImpl {
	t.Helper()

	proxy := analytics.NewOpenTelemetryProxy(t.Context(), settings)
	impl, ok := proxy.(*analytics.OpenTelemetryProxyImpl)
	require.True(
		t,
		ok,
		"expected *OpenTelemetryProxyImpl when analytics is enabled",
	)

	t.Cleanup(func() {
		require.NoError(t, impl.Shutdown(context.Background()))
	})
	return impl
}

func TestOpenTelemetryProxyImpl_RecordsDefaultAttributes(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.IncrementCounterAndLogEvent(
		t.Context(),
		"default_attrs_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, impl.Shutdown(context.Background()))

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

func TestOpenTelemetryProxyImpl_With_LowCardinalityAttributes(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	derived := impl.With(nil, analytics.LowCardinalityAttributes{
		ErrorType: "MyError",
	})
	derived.IncrementCounterAndLogEvent(
		t.Context(),
		"low_card_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	log, ok := findLog(captured.logs, "low_card_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "MyError", log.Attributes["error.type"])

	metric, ok := findMetric(captured.metrics, "low_card_event")
	require.True(t, ok, "expected a metric for the event")
	assert.Equal(t, "MyError", metric.Attributes["error.type"])
}

func TestOpenTelemetryProxyImpl_With_InheritsAndIgnoresEmptyFields(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	// Chained derivation: each child inherits its parent's attributes,
	// and empty fields must not overwrite inherited or default values.
	derived := impl.
		With(nil, analytics.LowCardinalityAttributes{
			WandbVersion: "custom-version",
		}).
		With(nil, analytics.LowCardinalityAttributes{}).
		With(nil, analytics.LowCardinalityAttributes{
			ErrorType: "MyError",
		})
	derived.RecordLog(
		t.Context(),
		"empty_fields_event",
		nil,
		analytics.LowCardinalityAttributes{},
		otellogapi.SeverityInfo,
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	log, ok := findLog(captured.logs, "empty_fields_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "custom-version", log.Attributes["wandb_version"])
	assert.Equal(t, runtime.Version(), log.Attributes["go_version"])
	assert.Equal(t, "MyError", log.Attributes["error.type"])
}

func TestOpenTelemetryProxyImpl_With_HighCardinalityLogsOnly(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	derived := impl.With(
		map[string]string{"arbitrary_key": "value"},
		analytics.LowCardinalityAttributes{},
	)
	derived.IncrementCounterAndLogEvent(
		t.Context(),
		"high_card_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	// High-cardinality attributes are attached to log records...
	log, ok := findLog(captured.logs, "high_card_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "value", log.Attributes["arbitrary_key"])

	// ...but never to metrics, where they would blow up cardinality.
	metric, ok := findMetric(captured.metrics, "high_card_event")
	require.True(t, ok, "expected a metric for the event")
	assert.NotContains(t, metric.Attributes, "arbitrary_key")
}

func TestOpenTelemetryProxyImpl_With_DoesNotAffectParent(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.With(
		map[string]string{"child_key": "child-value"},
		analytics.LowCardinalityAttributes{ErrorType: "ChildError"},
	)
	impl.IncrementCounterAndLogEvent(
		t.Context(),
		"parent_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	// Records emitted through the parent must not carry the
	// child's attributes.
	log, ok := findLog(captured.logs, "parent_event")
	require.True(t, ok, "expected a log for the parent event")
	assert.NotContains(t, log.Attributes, "child_key")
	assert.NotContains(t, log.Attributes, "error.type")

	metric, ok := findMetric(captured.metrics, "parent_event")
	require.True(t, ok, "expected a metric for the parent event")
	assert.NotContains(t, metric.Attributes, "error.type")
}

func TestOpenTelemetryProxyImpl_With_SharesShutdown(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	derived := impl.With(nil, analytics.LowCardinalityAttributes{})
	require.NoError(t, impl.Shutdown(context.Background()))

	// After the root proxy shuts down, derived recorders are no-ops.
	derived.RecordLog(
		t.Context(),
		"after_shutdown",
		nil,
		analytics.LowCardinalityAttributes{},
		otellogapi.SeverityInfo,
	)

	_, ok := findLog(captured.logs, "after_shutdown")
	assert.False(t, ok, "expected no log from a derived recorder after shutdown")
}

func TestOpenTelemetryProxyImpl_PerRecordAttributesOverrideContext(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	derived := impl.With(
		map[string]string{"test_key": "from-context"},
		analytics.LowCardinalityAttributes{WandbVersion: "from-context"},
	)
	derived.RecordLog(
		t.Context(),
		"override_event",
		map[string]string{"test_key": "from-argument"},
		analytics.LowCardinalityAttributes{WandbVersion: "from-argument"},
		otellogapi.SeverityInfo,
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	log, ok := findLog(captured.logs, "override_event")
	require.True(t, ok, "expected a log for the event")
	assert.Equal(t, "from-argument", log.Attributes["wandb_version"])
	assert.Equal(t, "from-argument", log.Attributes["test_key"])
}

func TestOpenTelemetryProxyImpl_PerRecordAttributesDoNotPersist(
	t *testing.T,
) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.RecordLog(
		t.Context(),
		"with_overrides",
		map[string]string{"test_key": "per-record"},
		analytics.LowCardinalityAttributes{WandbVersion: "per-record"},
		otellogapi.SeverityInfo,
	)
	impl.RecordLog(
		t.Context(),
		"without_overrides",
		nil,
		analytics.LowCardinalityAttributes{},
		otellogapi.SeverityInfo,
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	// Per-record attributes must not leak into the telemetry context
	// and affect subsequent records.
	log, ok := findLog(captured.logs, "without_overrides")
	require.True(t, ok, "expected a log for the second record")
	assert.Equal(t, version.Version, log.Attributes["wandb_version"])
	assert.NotContains(t, log.Attributes, "test_key")
}

func TestNewOpenTelemetryProxy_NoAPIKey_ReturnsNoopProxy(t *testing.T) {
	proxy := analytics.NewOpenTelemetryProxy(
		t.Context(),
		newTestSettings("http://example.invalid", ""),
	)

	_, ok := proxy.(analytics.NoopOpenTelemetryProxy)

	assert.True(t, ok, "expected NoopOpenTelemetryProxy when API key is empty")
}

func TestNewOpenTelemetryProxy_WithAPIKey_ReturnsImpl(t *testing.T) {
	proxy := analytics.NewOpenTelemetryProxy(
		t.Context(),
		newTestSettings("http://example.invalid", "test-api-key"),
	)

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
		analytics.LowCardinalityAttributes{},
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

	impl.IncrementCounterAndLogEvent(
		t.Context(),
		"an_event",
		map[string]string{
			"custom": "value",
		},
		analytics.LowCardinalityAttributes{ErrorType: "X"},
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	// verify metric emitted
	metric, ok := findMetric(captured.metrics, "an_event")
	require.True(t, ok, "expected a metric named after the event")
	assert.Equal(t, int64(1), metric.Value)
	assert.Equal(t, "X", metric.Attributes["error.type"])

	// verify log emitted
	log, ok := findLog(captured.logs, "an_event")
	require.True(t, ok, "expected a log named after the event")
	assert.Equal(t, otellogapi.SeverityInfo, log.Severity)
	assert.Equal(t, "value", log.Attributes["custom"])
}

func TestOpenTelemetryProxyImpl_SendsAPIKeyAuth(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.IncrementCounterAndLogEvent(
		t.Context(),
		"authenticated_event",
		nil,
		analytics.LowCardinalityAttributes{},
	)
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

func TestOpenTelemetryProxyImpl_Error(t *testing.T) {
	url, captured := newOTLPTestServer(t)
	impl := startProxy(t, url, "test-api-key")

	impl.Error(
		t.Context(),
		"error-message",
		assert.AnError,
		"test-error-type",
	)
	require.NoError(t, impl.Shutdown(context.Background()))

	// verify metric emitted
	metric, ok := findMetric(captured.metrics, "error")
	require.True(t, ok, "expected an error metric")
	assert.Equal(t, int64(1), metric.Value)
	assert.NotEmpty(t, metric.Attributes["error.type"])

	// verify log emitted
	log, ok := findLog(captured.logs, "error-message")
	require.True(t, ok, "expected an error log")
	assert.Equal(t, otellogapi.SeverityError, log.Severity)
	assert.Equal(t,
		"test-error-type",
		log.Attributes["error.type"],
	)
	assert.Equal(t, assert.AnError.Error(), log.Attributes["error.message"])
	assert.NotEmpty(t, log.Attributes["error.stacktrace"])
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

	impl.RecordLog(
		t.Context(),
		"after",
		nil,
		analytics.LowCardinalityAttributes{},
		otellogapi.SeverityInfo,
	)

	_, ok := findLog(captured.logs, "after")
	assert.False(t, ok, "expected no log to be exported after shutdown")
}
