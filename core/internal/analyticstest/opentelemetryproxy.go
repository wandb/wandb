package analyticstest

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"slices"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"
	otellogapi "go.opentelemetry.io/otel/log"
	collogspb "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	colmetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/analytics"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Log is a OTLP log record received by an OpenTelemetryProxyTest,
// with its body, severity, and attributes extracted.
type Log struct {
	Body       string
	Severity   otellogapi.Severity
	Attributes map[string]string
}

// Metric is a OTLP metric data point received by an OpenTelemetryProxyTest,
// with its name, value, and attributes extracted.
type Metric struct {
	Name       string
	Value      int64
	Attributes map[string]string
}

// Request is an HTTP request received by an OpenTelemetryProxyTest.
type Request struct {
	Path          string
	Authorization string
	Headers       http.Header
	URLHost       string
}

// OpenTelemetryProxyTest is an OpenTelemetry proxy and test OTLP collector.
type OpenTelemetryProxyTest struct {
	*analytics.OpenTelemetryProxy

	server *httptest.Server

	mu       sync.Mutex
	logs     []Log
	metrics  []Metric
	requests []Request
}

// Requests returns a snapshot of received HTTP requests.
func (s *OpenTelemetryProxyTest) Requests() []Request {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.requests)
}

// FindLog returns the first received log with the given body.
func (s *OpenTelemetryProxyTest) FindLog(body string) (Log, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, log := range s.logs {
		if log.Body == body {
			return log, true
		}
	}
	return Log{}, false
}

// FindMetric returns the first received metric with the given name.
func (s *OpenTelemetryProxyTest) FindMetric(name string) (Metric, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, metric := range s.metrics {
		if metric.Name == name {
			return metric, true
		}
	}
	return Metric{}, false
}

// NewOpenTelemetryProxyTest creates an OpenTelemetry proxy backed by an OTLP
// test server.
//
// Call Shutdown before asserting exports to flush the proxy's batch processors.
func NewOpenTelemetryProxyTest(
	t *testing.T,
) *OpenTelemetryProxyTest {
	t.Helper()

	testProxy := &OpenTelemetryProxyTest{}
	testProxy.server = httptest.NewServer(http.HandlerFunc(testProxy.handleExport))
	t.Cleanup(testProxy.server.Close)

	settings := wbsettings.From(&spb.Settings{
		BaseUrl: wrapperspb.String(testProxy.server.URL),
		ApiKey:  wrapperspb.String("test-api-key"),
	})
	proxy := analytics.NewOpenTelemetryProxy(t.Context(), settings)
	require.NotNil(t, proxy)
	t.Cleanup(func() {
		require.NoError(t, proxy.Shutdown(context.Background()))
	})
	testProxy.OpenTelemetryProxy = proxy
	return testProxy
}

func (s *OpenTelemetryProxyTest) handleExport(w http.ResponseWriter, r *http.Request) {
	s.addRequest(r)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "read export body", http.StatusInternalServerError)
		return
	}

	switch r.URL.Path {
	case "/sdk/otel/v1/logs":
		if err := s.addLogs(body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
	case "/sdk/otel/v1/metrics":
		if err := s.addMetrics(body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
	default:
		http.Error(w, "unexpected export path", http.StatusNotFound)
		return
	}

	w.WriteHeader(http.StatusOK)
}

func (s *OpenTelemetryProxyTest) addLogs(body []byte) error {
	var request collogspb.ExportLogsServiceRequest
	if err := proto.Unmarshal(body, &request); err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	for _, resourceLogs := range request.GetResourceLogs() {
		for _, scopeLogs := range resourceLogs.GetScopeLogs() {
			for _, logRecord := range scopeLogs.GetLogRecords() {
				s.logs = append(s.logs, Log{
					Body:       logRecord.GetBody().GetStringValue(),
					Severity:   otellogapi.Severity(logRecord.GetSeverityNumber()),
					Attributes: keyValuesToMap(logRecord.GetAttributes()),
				})
			}
		}
	}
	return nil
}

func (s *OpenTelemetryProxyTest) addMetrics(body []byte) error {
	var request colmetricspb.ExportMetricsServiceRequest
	if err := proto.Unmarshal(body, &request); err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	for _, resourceMetrics := range request.GetResourceMetrics() {
		for _, scopeMetrics := range resourceMetrics.GetScopeMetrics() {
			for _, metric := range scopeMetrics.GetMetrics() {
				for _, dataPoint := range metric.GetSum().GetDataPoints() {
					s.metrics = append(s.metrics, Metric{
						Name:       metric.GetName(),
						Value:      dataPoint.GetAsInt(),
						Attributes: keyValuesToMap(dataPoint.GetAttributes()),
					})
				}
			}
		}
	}
	return nil
}

func (s *OpenTelemetryProxyTest) addRequest(request *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.requests = append(s.requests, Request{
		Path:          request.URL.Path,
		Authorization: request.Header.Get("Authorization"),
		Headers:       request.Header.Clone(),
		URLHost:       request.URL.Host,
	})
}

func keyValuesToMap(keyValues []*commonpb.KeyValue) map[string]string {
	attributes := make(map[string]string, len(keyValues))
	for _, keyValue := range keyValues {
		attributes[keyValue.GetKey()] = keyValue.GetValue().GetStringValue()
	}
	return attributes
}
