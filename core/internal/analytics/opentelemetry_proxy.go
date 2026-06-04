// Package analytics provides an OpenTelemetry proxy that sends metrics, logs
// to the W&B backend's OpenTelemetry proxy API.
package analytics

import (
	"context"
	"fmt"
	"maps"
	"net/http"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	otellogapi "go.opentelemetry.io/otel/log"
	"go.opentelemetry.io/otel/log/global"
	otelmetric "go.opentelemetry.io/otel/metric"
	otellog "go.opentelemetry.io/otel/sdk/log"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"

	"github.com/wandb/wandb/core/internal/version"
)

const (
	defaultExportIntervalMs = 500
	defaultTimeout          = 1 * time.Second
	serviceName             = "wandb-core"
	metricsPath             = "/sdk/otel/v1/metrics"
	logsPath                = "/sdk/otel/v1/logs"
)

// Low-cardinality attribute keys.
// These are emitted as metric dimensions,
// so their values must come from a small, bounded set.
const (
	attributeGoVersion       = "go_version"
	attributeWandbVersion    = "wandb_version"
	attributeOperatingSystem = "operating_system"
	attributeExceptionType   = "exception.type"
)

var allowedLowCardinalityKeys = map[string]struct{}{
	attributeGoVersion:       {},
	attributeWandbVersion:    {},
	attributeOperatingSystem: {},
	attributeExceptionType:   {},
}

// enabled gates OpenTelemetryProxy in this process.
var enabled atomic.Bool

func init() {
	enabled.Store(true)
}

// SetEnabled turns analytics on or off for the whole process.
//
// It should be called once during startup, before any OpenTelemetryProxy is
// created, and is safe to call concurrently.
func SetEnabled(v bool) {
	enabled.Store(v)
}

// TelemetryContext holds persistent attributes added to all telemetry records.
//
// Attributes are split into two buckets:
//
//   - Low-cardinality attributes are a small, bounded set of values
//     (e.g. wandb_version, go_version, operating_system).
//     These are restricted to a known set of keys,
//
//   - High-cardinality attributes are an unbounded set of values.
//     These are attached to log records where high cardinality is acceptable.
type TelemetryContext struct {
	mu sync.RWMutex

	lowCardinalityAttributes  map[string]string
	highCardinalityAttributes map[string]string
}

func newTelemetryContext() *TelemetryContext {
	return &TelemetryContext{
		lowCardinalityAttributes: map[string]string{
			attributeWandbVersion:    version.Version,
			attributeGoVersion:       runtime.Version(),
			attributeOperatingSystem: runtime.GOOS,
		},
		highCardinalityAttributes: map[string]string{},
	}
}

// AddLowCardinalityAttributes merges the provided attributes into the context.
//
// Only keys in the allow-list are accepted;
// any other keys are silently dropped.
func (s *TelemetryContext) AddLowCardinalityAttributes(
	attributes map[string]string,
) {
	if len(attributes) == 0 {
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	for k, v := range attributes {
		if _, ok := allowedLowCardinalityKeys[k]; ok {
			s.lowCardinalityAttributes[k] = v
		}
	}
}

// AddHighCardinalityAttributes merges caller-supplied high-cardinality attributes
// into the context.
func (s *TelemetryContext) AddHighCardinalityAttributes(
	attributes map[string]string,
) {
	if len(attributes) == 0 {
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	maps.Copy(s.highCardinalityAttributes, attributes)
}

// lowCardinalitySnapshot returns a snapshot of the context's low-cardinality attributes
// merged with the provided attributes. Keys in the provided attributes override
// the context's attributes.
//
// The provided attributes are checked against the low-cardinality allow-list.
// Any key not in the allow-list is silently dropped.
func (s *TelemetryContext) lowCardinalitySnapshot(
	attributes map[string]string,
) map[string]string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	out := make(
		map[string]string,
		len(s.lowCardinalityAttributes)+len(attributes),
	)
	maps.Copy(out, s.lowCardinalityAttributes)

	// Filter out any attributes not in our low-cardinality allow-list.
	for k, v := range attributes {
		if _, ok := allowedLowCardinalityKeys[k]; ok {
			out[k] = v
		}
	}
	return out
}

// highCardinalitySnapshot returns a snapshot of the context's high-cardinality attributes
// merged with the provided attributes.
func (s *TelemetryContext) highCardinalitySnapshot(
	attributes map[string]string,
) map[string]string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	out := make(
		map[string]string,
		len(s.highCardinalityAttributes)+len(attributes),
	)
	maps.Copy(out, s.highCardinalityAttributes)
	maps.Copy(out, attributes)
	return out
}

// OpenTelemetryProxy records OpenTelemetry events (metrics and logs).
type OpenTelemetryProxy interface {
	Start(ctx context.Context) error
	Shutdown(ctx context.Context) error
	RecordLog(body string, attributes map[string]string, severity otellogapi.Severity)
	RecordMetricAndLogEvent(event string, attributes map[string]string)
	Exception(message string, err error)
}

var (
	_ OpenTelemetryProxy = (*OpenTelemetryProxyImpl)(nil)
	_ OpenTelemetryProxy = noopOpenTelemetryProxy{}
)

// OpenTelemetryProxyImpl sends metrics, logs events through the W&B
// backend's OpenTelemetry proxy API.
type OpenTelemetryProxyImpl struct {
	mu sync.Mutex

	// endpoint is the URL of the OpenTelemetry proxy API.
	endpoint string

	// logProvider is the OpenTelemetry log provider.
	logProvider *otellog.LoggerProvider
	// meterProvider is the OpenTelemetry meter provider.
	meterProvider *metric.MeterProvider

	// httpClient is the HTTP client used to send metrics and logs
	// to the OpenTelemetry proxy API.
	httpClient *http.Client

	// telemetryContext is the context containing attributes
	// which are added to telemetry records.
	telemetryContext *TelemetryContext

	// shutdown is set once the providers have been shut down,
	// after which recording methods become no-ops.
	shutdown atomic.Bool
}

// NewOpenTelemetryProxy returns an OpenTelemetryProxy for the given endpoint.
//
// When analytics is disabled (see SetEnabled), a no-op proxy is returned so
// no providers are created and nothing is recorded.
func NewOpenTelemetryProxy(endpoint string) OpenTelemetryProxy {
	if !enabled.Load() {
		return noopOpenTelemetryProxy{}
	}

	return &OpenTelemetryProxyImpl{
		endpoint:         endpoint,
		telemetryContext: newTelemetryContext(),
		httpClient: &http.Client{
			Timeout: defaultTimeout,
		},
	}
}

// Start implements OpenTelemetryProxy.Start.
//
// It initializes the OpenTelemetry meter and log providers.
func (o *OpenTelemetryProxyImpl) Start(ctx context.Context) error {
	o.mu.Lock()
	defer o.mu.Unlock()

	res, err := resource.New(
		ctx,
		resource.WithAttributes(semconv.ServiceName(serviceName)),
	)
	if err != nil {
		return fmt.Errorf("create resource: %w", err)
	}

	if err := o.setupMetrics(ctx, res); err != nil {
		return err
	}
	if err := o.setupLogs(ctx, res); err != nil {
		return err
	}
	return nil
}

// setupMetrics sets up the OpenTelemetry meter provider, used to record metrics.
func (o *OpenTelemetryProxyImpl) setupMetrics(
	ctx context.Context,
	res *resource.Resource,
) error {
	exporter, err := otlpmetrichttp.New(ctx,
		otlpmetrichttp.WithEndpoint(o.endpoint),
		otlpmetrichttp.WithURLPath(metricsPath),
		otlpmetrichttp.WithTemporalitySelector(metric.DeltaTemporalitySelector),
	)
	if err != nil {
		return fmt.Errorf("create metric exporter: %w", err)
	}

	o.meterProvider = metric.NewMeterProvider(
		metric.WithResource(res),
		metric.WithReader(
			metric.NewPeriodicReader(exporter,
				metric.WithInterval(defaultExportIntervalMs*time.Millisecond),
			),
		),
	)
	otel.SetMeterProvider(o.meterProvider)
	return nil
}

// setupLogs sets up the OpenTelemetry log provider, used to record logs.
func (o *OpenTelemetryProxyImpl) setupLogs(
	ctx context.Context,
	res *resource.Resource,
) error {
	exporter, err := otlploghttp.New(ctx,
		otlploghttp.WithEndpoint(o.endpoint),
		otlploghttp.WithURLPath(logsPath),
	)
	if err != nil {
		return fmt.Errorf("create log exporter: %w", err)
	}

	o.logProvider = otellog.NewLoggerProvider(
		otellog.WithResource(res),
		otellog.WithProcessor(otellog.NewBatchProcessor(exporter)),
	)
	global.SetLoggerProvider(o.logProvider)
	return nil
}

// Shutdown implements OpenTelemetryProxy.Shutdown.
//
// It flushes any pending records and shuts down all providers.
// It should be called once when the proxy is no longer needed.
// Additional calls are no-ops.
func (o *OpenTelemetryProxyImpl) Shutdown(ctx context.Context) error {
	if !o.shutdown.CompareAndSwap(false, true) {
		return nil
	}

	o.mu.Lock()
	defer o.mu.Unlock()

	var errs []error
	if o.meterProvider != nil {
		if err := o.meterProvider.Shutdown(ctx); err != nil {
			errs = append(errs, err)
		}
	}
	if o.logProvider != nil {
		if err := o.logProvider.Shutdown(ctx); err != nil {
			errs = append(errs, err)
		}
	}
	if len(errs) > 0 {
		return fmt.Errorf("shutdown errors: %v", errs)
	}
	return nil
}

// recordCount increments a counter metric by 1.
//
// The caller-supplied attributes are checked against the low-cardinality allow-list.
// Any key not in the allow-list is dropped.
func (o *OpenTelemetryProxyImpl) recordCount(
	name string,
	attributes map[string]string,
) {
	if o.shutdown.Load() {
		return
	}

	meter := otel.Meter(serviceName)
	counter, err := meter.Int64Counter(name)
	if err != nil {
		return
	}

	counter.Add(
		context.Background(),
		1,
		toOTelAttrs(o.telemetryContext.lowCardinalitySnapshot(attributes)),
	)
}

// RecordLog implements OpenTelemetryProxy.RecordLog.
// It emits an OpenTelemetry log record with the specified severity level.
//
// The log record contains the attributes from the current context,
// in addition to the caller-supplied attributes.
func (o *OpenTelemetryProxyImpl) RecordLog(
	body string,
	attributes map[string]string,
	severity otellogapi.Severity,
) {
	if o.shutdown.Load() {
		return
	}

	logger := global.GetLoggerProvider().Logger(serviceName)
	var record otellogapi.Record
	record.SetBody(otellogapi.StringValue(body))
	record.SetSeverity(severity)

	attrs := o.telemetryContext.lowCardinalitySnapshot(nil)
	maps.Copy(attrs, o.telemetryContext.highCardinalitySnapshot(attributes))
	if len(attrs) > 0 {
		kvs := make([]otellogapi.KeyValue, 0, len(attrs))
		for k, v := range attrs {
			kvs = append(kvs, otellogapi.String(k, v))
		}
		record.AddAttributes(kvs...)
	}

	logger.Emit(context.Background(), record)
}

// RecordMetricAndLogEvent implements OpenTelemetryProxy.RecordMetricAndLogEvent.
// It records both a counter metric with the context's low-cardinality attributes
// and a log record with the context's attributes
// plus the caller-supplied attributes under the same name.
func (o *OpenTelemetryProxyImpl) RecordMetricAndLogEvent(
	event string,
	attributes map[string]string,
) {
	o.recordCount(event, attributes)
	o.RecordLog(event, attributes, otellogapi.SeverityInfo)
}

// Exception implements OpenTelemetryProxy.Exception.
//
// It records an error as both a counter metric and an error log.
//
// The counter metric has the name "exception" and contains
// the low-cardinality attributes from the current context plus an
// "exception.type" attribute (the error's type) so the
// rate of each error type can be aggregated and graphed.
//
// The log record contains the attributes from the current context, plus
// "exception.type", "exception.message", and "exception.stacktrace". The
// stack trace is captured at the point Exception is called.
func (o *OpenTelemetryProxyImpl) Exception(message string, err error) {
	exceptionType := "unknown"
	exceptionMessage := ""
	if err != nil {
		exceptionType = fmt.Sprintf("%T", err)
		exceptionMessage = err.Error()
	}

	o.recordCount("exception", map[string]string{
		"exception.type": exceptionType,
	})

	logAttrs := map[string]string{
		"exception.type":       exceptionType,
		"exception.message":    exceptionMessage,
		"exception.stacktrace": captureStacktrace(),
	}
	o.RecordLog(message, logAttrs, otellogapi.SeverityError)
}

// noopOpenTelemetryProxy is a OpenTelemetryProxy that does nothing.
type noopOpenTelemetryProxy struct{}

// Start implements OpenTelemetryProxy.Start.
func (noopOpenTelemetryProxy) Start(context.Context) error { return nil }

// Shutdown implements OpenTelemetryProxy.Shutdown.
func (noopOpenTelemetryProxy) Shutdown(context.Context) error { return nil }

// RecordLog implements OpenTelemetryProxy.RecordLog.
func (noopOpenTelemetryProxy) RecordLog(string, map[string]string, otellogapi.Severity) {}

// RecordMetricAndLogEvent implements OpenTelemetryProxy.RecordMetricAndLogEvent.
func (noopOpenTelemetryProxy) RecordMetricAndLogEvent(string, map[string]string) {}

// Exception implements OpenTelemetryProxy.Exception.
func (noopOpenTelemetryProxy) Exception(string, error) {}

// captureStacktrace returns a formatted stack trace of the calling goroutine,
// starting at the caller of Exception.
//
// This uses only the standard library: it captures the current call stack
// rather than the site where err was created (which Go does not record for
// plain errors.New/fmt.Errorf values).
func captureStacktrace() string {
	pcs := make([]uintptr, 64)
	// Skip runtime.Callers, captureStacktrace, and Exception so the trace
	// starts at the code that reported the exception.
	n := runtime.Callers(3, pcs)
	if n == 0 {
		return ""
	}
	return formatStackPCs(pcs[:n])
}

// formatStackPCs symbolizes program counters into a human-readable, multi-line
// stack trace of the form:
//
//	package/path.Function
//		/abs/path/file.go:123
func formatStackPCs(pcs []uintptr) string {
	var b strings.Builder
	frames := runtime.CallersFrames(pcs)
	for {
		frame, more := frames.Next()
		fmt.Fprintf(
			&b,
			"%s\n\t%s:%d\n",
			frame.Function,
			frame.File,
			frame.Line,
		)
		if !more {
			break
		}
	}
	return b.String()
}

// toOTelAttrs converts a map of string attributes
// to an otelmetric.WithAttributes option.
func toOTelAttrs(attrs map[string]string) otelmetric.MeasurementOption {
	kvs := make([]attribute.KeyValue, 0, len(attrs))
	for k, v := range attrs {
		kvs = append(kvs, attribute.String(k, v))
	}
	return otelmetric.WithAttributes(kvs...)
}
