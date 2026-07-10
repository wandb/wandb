// Package analytics provides an OpenTelemetry proxy that sends metrics, logs
// to the W&B backend's OpenTelemetry proxy API.
package analytics

import (
	"cmp"
	"context"
	"crypto/tls"
	"fmt"
	"log/slog"
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

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
)

const (
	defaultExportIntervalMs = 500
	defaultTimeout          = 1 * time.Second
	serviceName             = "wandb-core"
	metricsPath             = "/sdk/otel/v1/metrics"
	logsPath                = "/sdk/otel/v1/logs"
)

// ConfigureOTelErrorHandler routes OpenTelemetry SDK errors to the core logger.
func ConfigureOTelErrorHandler() {
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) {
		slog.Error(
			"analytics: failed to send telemetry to backend proxy",
			"error", err,
		)
	}))
}

// LowCardinalityAttributes is the fixed set of low-cardinality attributes
// that can be added to the telemetry context.
type LowCardinalityAttributes struct {
	GoVersion       string
	WandbVersion    string
	OperatingSystem string
	ErrorType       string
}

// merge overwrites attrs with the non-empty fields of other.
func (attrs *LowCardinalityAttributes) merge(other LowCardinalityAttributes) {
	attrs.GoVersion = cmp.Or(other.GoVersion, attrs.GoVersion)
	attrs.WandbVersion = cmp.Or(other.WandbVersion, attrs.WandbVersion)
	attrs.OperatingSystem = cmp.Or(other.OperatingSystem, attrs.OperatingSystem)
	attrs.ErrorType = cmp.Or(other.ErrorType, attrs.ErrorType)
}

func (attrs LowCardinalityAttributes) toMap() map[string]string {
	out := make(map[string]string, 4)
	if attrs.GoVersion != "" {
		out["go_version"] = attrs.GoVersion
	}
	if attrs.WandbVersion != "" {
		out["wandb_version"] = attrs.WandbVersion
	}
	if attrs.OperatingSystem != "" {
		out["operating_system"] = attrs.OperatingSystem
	}
	if attrs.ErrorType != "" {
		out["error.type"] = attrs.ErrorType
	}
	return out
}

// disabled gates OpenTelemetryProxy in this process.
var disabled atomic.Bool

// Disable turns analytics off for the whole process.
//
// Once this function is called, no further telemetry will be recorded.
func Disable() {
	disabled.Store(true)
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
	// mu protects reading and writing to the attribute maps.
	// Because writing attributes should happen infrequently,
	// we use a read-write lock to allow multiple readers simultaneously.
	mu sync.RWMutex

	// lowCardinalityAttributes is a bounded set of attributes.
	// these attributes are added to all telemetry records.
	lowCardinalityAttributes LowCardinalityAttributes

	// highCardinalityAttributes is an unbounded set of attributes.
	// these attributes are added to telemetry records
	// where high cardinality is acceptable, such as log records.
	highCardinalityAttributes map[string]string
}

func NewTelemetryContext() *TelemetryContext {
	lowCardinalityAttributes := LowCardinalityAttributes{
		WandbVersion:    version.Version,
		GoVersion:       runtime.Version(),
		OperatingSystem: runtime.GOOS,
	}

	return &TelemetryContext{
		lowCardinalityAttributes:  lowCardinalityAttributes,
		highCardinalityAttributes: map[string]string{},
	}
}

// LowCardinalitySnapshot returns a snapshot of the context's low-cardinality
// attributes merged with overrides.
//
// Non-empty fields in overrides take precedence over the context's attributes.
func (s *TelemetryContext) lowCardinalitySnapshot(
	overrides LowCardinalityAttributes,
) map[string]string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	snapshot := s.lowCardinalityAttributes.toMap()
	maps.Copy(snapshot, overrides.toMap())
	return snapshot
}

// HighCardinalitySnapshot returns a snapshot of the context's high-cardinality attributes
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
	// Shutdown flushes any pending records and shuts down all providers.
	// It should be called once when the proxy is no longer needed.
	// Additional calls are no-ops.
	Shutdown(ctx context.Context) error

	// RecordLog emits an OpenTelemetry log record with the specified severity level.
	//
	// The log record contains the attributes from the current telemetry context,
	// in addition to the caller-supplied attributes.
	RecordLog(
		ctx context.Context,
		body string,
		attributes map[string]string,
		lowCardinalityAttributes LowCardinalityAttributes,
		severity otellogapi.Severity,
	)

	// IncrementCounterAndLogEvent increments a counter metric by 1
	// with the telemetry context's low-cardinality attributes
	//
	// It additionally records a log record with the telemetry
	// context's attributes plus the caller-supplied attributes under the same
	// name.
	IncrementCounterAndLogEvent(
		ctx context.Context,
		event string,
		attributes map[string]string,
		lowCardinalityAttributes LowCardinalityAttributes,
	)

	// Error records an error as both a counter metric and an error log.
	//
	// The counter metric has the name "error" and contains
	// the low-cardinality attributes from the current telemetry context plus an
	// "error.type" attribute (the caller-supplied error type) so the
	// rate of each error type can be aggregated and graphed.
	//
	// The log record contains the attributes from the current telemetry context,
	// plus "error.type", "error.message", and "error.stacktrace".
	// The stack trace is captured at the point Error is called.
	Error(ctx context.Context, message string, err error, errorType string)

	// SetHighCardinalityAttributes merges caller-supplied high-cardinality attributes
	// into the context.
	SetHighCardinalityAttributes(attributes map[string]string)

	// SetLowCardinalityAttributes merges the provided attributes into the context.
	SetLowCardinalityAttributes(attributes LowCardinalityAttributes)
}

var (
	_ OpenTelemetryProxy = (*OpenTelemetryProxyImpl)(nil)
	_ OpenTelemetryProxy = NoopOpenTelemetryProxy{}
)

// OpenTelemetryProxyImpl sends metrics, logs events through the W&B
// backend's OpenTelemetry proxy API.
type OpenTelemetryProxyImpl struct {
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
// When analytics is disabled or no API key is available, a no-op proxy is
// returned so no providers are created and nothing is recorded.
func NewOpenTelemetryProxy(
	ctx context.Context,
	wandbSettings *settings.Settings,
) OpenTelemetryProxy {
	if disabled.Load() || wandbSettings.GetAPIKey() == "" {
		return NoopOpenTelemetryProxy{}
	}

	proxy := &OpenTelemetryProxyImpl{
		endpoint:         wandbSettings.GetBaseURL(),
		telemetryContext: NewTelemetryContext(),
		httpClient:       newOTLPHTTPClient(wandbSettings),
	}
	if err := proxy.initializeOTelResources(ctx); err != nil {
		return NoopOpenTelemetryProxy{}
	}
	return proxy
}

func newOTLPHTTPClient(wandbSettings *settings.Settings) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = clients.ProxyFn(
		wandbSettings.GetHTTPProxy(),
		wandbSettings.GetHTTPSProxy(),
	)
	if wandbSettings.IsInsecureDisableSSL() {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	extraHeaders := make(http.Header, len(wandbSettings.GetExtraHTTPHeaders()))
	for key, value := range wandbSettings.GetExtraHTTPHeaders() {
		extraHeaders.Set(key, value)
	}
	if header := extraHeaders.Get("Proxy-Authorization"); header != "" {
		transport.ProxyConnectHeader = http.Header{
			"Proxy-Authorization": []string{header},
		}
	}

	client := &http.Client{
		Timeout: defaultTimeout,
	}
	client.Transport = httplayers.WrapRoundTripper(
		transport,
		httplayers.Concat(
			httplayers.ExtraHeaders(extraHeaders),
			api.NewAPIKeyCredentialProvider(wandbSettings.GetAPIKey()),
		),
	)
	return client
}

// initializeOTelResources initializes the OpenTelemetry meter and log providers.
func (o *OpenTelemetryProxyImpl) initializeOTelResources(ctx context.Context) error {
	res, err := resource.New(
		ctx,
		resource.WithAttributes(semconv.ServiceName(serviceName)),
	)
	if err != nil {
		return fmt.Errorf("create resource: %w", err)
	}

	meterProvider, err := o.setupMetrics(ctx, res)
	if err != nil {
		return err
	}
	logProvider, err := o.setupLogs(ctx, res)
	if err != nil {
		if shutdownErr := shutdownTelemetryProviders(
			context.Background(),
			meterProvider,
			nil,
		); shutdownErr != nil {
			return fmt.Errorf("%w; cleanup failed: %v", err, shutdownErr)
		}
		return err
	}

	o.meterProvider = meterProvider
	o.logProvider = logProvider
	otel.SetMeterProvider(o.meterProvider)
	global.SetLoggerProvider(o.logProvider)

	return nil
}

// setupMetrics sets up the OpenTelemetry meter provider, used to record metrics.
func (o *OpenTelemetryProxyImpl) setupMetrics(
	ctx context.Context,
	res *resource.Resource,
) (*metric.MeterProvider, error) {
	exporter, err := otlpmetrichttp.New(ctx,
		otlpmetrichttp.WithEndpointURL(o.endpoint),
		otlpmetrichttp.WithURLPath(metricsPath),
		otlpmetrichttp.WithHTTPClient(o.httpClient),
		otlpmetrichttp.WithTemporalitySelector(metric.DeltaTemporalitySelector),
	)
	if err != nil {
		return nil, fmt.Errorf("create metric exporter: %w", err)
	}

	return metric.NewMeterProvider(
		metric.WithResource(res),
		metric.WithReader(
			metric.NewPeriodicReader(exporter,
				metric.WithInterval(defaultExportIntervalMs*time.Millisecond),
			),
		),
	), nil
}

// setupLogs sets up the OpenTelemetry log provider, used to record logs.
func (o *OpenTelemetryProxyImpl) setupLogs(
	ctx context.Context,
	res *resource.Resource,
) (*otellog.LoggerProvider, error) {
	exporter, err := otlploghttp.New(ctx,
		otlploghttp.WithEndpointURL(o.endpoint),
		otlploghttp.WithURLPath(logsPath),
		otlploghttp.WithHTTPClient(o.httpClient),
	)
	if err != nil {
		return nil, fmt.Errorf("create log exporter: %w", err)
	}

	return otellog.NewLoggerProvider(
		otellog.WithResource(res),
		otellog.WithProcessor(otellog.NewBatchProcessor(exporter)),
	), nil
}

func shutdownTelemetryProviders(
	ctx context.Context,
	meterProvider *metric.MeterProvider,
	logProvider *otellog.LoggerProvider,
) error {
	var errs []error
	if meterProvider != nil {
		if err := meterProvider.Shutdown(ctx); err != nil {
			errs = append(errs, err)
		}
	}
	if logProvider != nil {
		if err := logProvider.Shutdown(ctx); err != nil {
			errs = append(errs, err)
		}
	}
	if len(errs) > 0 {
		return fmt.Errorf("shutdown errors: %v", errs)
	}
	return nil
}

// Shutdown implements OpenTelemetryProxy.Shutdown.
func (o *OpenTelemetryProxyImpl) Shutdown(ctx context.Context) error {
	if !o.shutdown.CompareAndSwap(false, true) {
		return nil
	}

	meterProvider := o.meterProvider
	logProvider := o.logProvider
	return shutdownTelemetryProviders(ctx, meterProvider, logProvider)
}

// incrementCounter increments a counter metric by 1.
func (o *OpenTelemetryProxyImpl) incrementCounter(
	ctx context.Context,
	name string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if o.shutdown.Load() {
		return
	}

	meter := otel.Meter(serviceName)
	counter, err := meter.Int64Counter(name)
	if err != nil {
		return
	}

	snapshot := o.telemetryContext.lowCardinalitySnapshot(lowCardinalityAttributes)
	counter.Add(
		ctx,
		1,
		toOTelAttrs(snapshot),
	)
}

// RecordLog implements OpenTelemetryProxy.RecordLog.
func (o *OpenTelemetryProxyImpl) RecordLog(
	ctx context.Context,
	body string,
	attributes map[string]string,
	lowCardinalityAttributes LowCardinalityAttributes,
	severity otellogapi.Severity,
) {
	if o.shutdown.Load() {
		return
	}

	logger := global.GetLoggerProvider().Logger(serviceName)
	var record otellogapi.Record
	record.SetBody(otellogapi.StringValue(body))
	record.SetSeverity(severity)

	snapshot := o.telemetryContext.lowCardinalitySnapshot(
		lowCardinalityAttributes,
	)
	logAttributes := o.telemetryContext.highCardinalitySnapshot(snapshot)
	maps.Copy(logAttributes, attributes)
	if len(logAttributes) > 0 {
		kvs := make([]otellogapi.KeyValue, 0, len(logAttributes))
		for k, v := range logAttributes {
			kvs = append(kvs, otellogapi.String(k, v))
		}
		record.AddAttributes(kvs...)
	}

	logger.Emit(ctx, record)
}

// IncrementCounterAndLogEvent implements OpenTelemetryProxy.IncrementCounterAndLogEvent.
func (o *OpenTelemetryProxyImpl) IncrementCounterAndLogEvent(
	ctx context.Context,
	event string,
	attributes map[string]string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	o.incrementCounter(ctx, event, lowCardinalityAttributes)
	o.RecordLog(
		ctx,
		event,
		attributes,
		lowCardinalityAttributes,
		otellogapi.SeverityInfo,
	)
}

// Error implements OpenTelemetryProxy.Error.
func (o *OpenTelemetryProxyImpl) Error(
	ctx context.Context,
	message string,
	err error,
	errorType string,
) {
	errorMessage := ""
	if err != nil {
		errorMessage = err.Error()
	}
	lowCardinalityAttributes := LowCardinalityAttributes{
		ErrorType: errorType,
	}

	o.incrementCounter(
		ctx,
		"error",
		lowCardinalityAttributes,
	)

	logAttrs := map[string]string{
		"error.type":       errorType,
		"error.message":    errorMessage,
		"error.stacktrace": captureStacktrace(),
	}
	o.RecordLog(
		ctx,
		message,
		logAttrs,
		lowCardinalityAttributes,
		otellogapi.SeverityError,
	)
}

// SetHighCardinalityAttributes implements OpenTelemetryProxy.SetHighCardinalityAttributes.
func (o *OpenTelemetryProxyImpl) SetHighCardinalityAttributes(attributes map[string]string) {
	o.telemetryContext.mu.Lock()
	defer o.telemetryContext.mu.Unlock()
	maps.Copy(o.telemetryContext.highCardinalityAttributes, attributes)
}

// SetLowCardinalityAttributes implements OpenTelemetryProxy.SetLowCardinalityAttributes.
func (o *OpenTelemetryProxyImpl) SetLowCardinalityAttributes(attributes LowCardinalityAttributes) {
	o.telemetryContext.mu.Lock()
	defer o.telemetryContext.mu.Unlock()
	o.telemetryContext.lowCardinalityAttributes.merge(attributes)
}

// noopOpenTelemetryProxy is a OpenTelemetryProxy that does nothing.
type NoopOpenTelemetryProxy struct{}

// Shutdown implements OpenTelemetryProxy.Shutdown.
func (NoopOpenTelemetryProxy) Shutdown(context.Context) error { return nil }

// RecordLog implements OpenTelemetryProxy.RecordLog.
func (NoopOpenTelemetryProxy) RecordLog(
	context.Context,
	string,
	map[string]string,
	LowCardinalityAttributes,
	otellogapi.Severity,
) {
}

// IncrementCounterAndLogEvent implements OpenTelemetryProxy.IncrementCounterAndLogEvent.
func (NoopOpenTelemetryProxy) IncrementCounterAndLogEvent(
	context.Context,
	string,
	map[string]string,
	LowCardinalityAttributes,
) {
}

// Error implements OpenTelemetryProxy.Error.
func (NoopOpenTelemetryProxy) Error(
	context.Context,
	string,
	error,
	string,
) {
}

// SetHighCardinalityAttributes implements OpenTelemetryProxy.SetHighCardinalityAttributes.
func (NoopOpenTelemetryProxy) SetHighCardinalityAttributes(map[string]string) {
}

// SetLowCardinalityAttributes implements OpenTelemetryProxy.SetLowCardinalityAttributes.
func (NoopOpenTelemetryProxy) SetLowCardinalityAttributes(LowCardinalityAttributes) {
}

// captureStacktrace returns a formatted stack trace of the calling goroutine,
// starting at the caller of Error.
//
// This uses only the standard library: it captures the current call stack
// rather than the site where err was created (which Go does not record for
// plain errors.New/fmt.Errorf values).
func captureStacktrace() string {
	pcs := make([]uintptr, 64)
	// Skip runtime.Callers, captureStacktrace, and Error so the trace
	// starts at the code that reported the error.
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
