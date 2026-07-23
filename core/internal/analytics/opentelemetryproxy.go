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
	"sync/atomic"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	otellogapi "go.opentelemetry.io/otel/log"
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
	ErrorOriginator string
}

// merge overwrites attrs with the non-empty fields of other.
func (attrs *LowCardinalityAttributes) merge(other LowCardinalityAttributes) {
	attrs.GoVersion = cmp.Or(other.GoVersion, attrs.GoVersion)
	attrs.WandbVersion = cmp.Or(other.WandbVersion, attrs.WandbVersion)
	attrs.OperatingSystem = cmp.Or(other.OperatingSystem, attrs.OperatingSystem)
	attrs.ErrorOriginator = cmp.Or(other.ErrorOriginator, attrs.ErrorOriginator)
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
	if attrs.ErrorOriginator != "" {
		out["error.originator"] = attrs.ErrorOriginator
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
	// lowCardinalityAttributes is a bounded set of attributes.
	// These attributes are added to all telemetry records.
	lowCardinalityAttributes LowCardinalityAttributes

	// highCardinalityAttributes is an unbounded set of attributes.
	// These attributes are added to telemetry records
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

// with returns a child context that inherits this context's attributes
// merged with the provided ones. The receiver is not modified.
//
// Non-empty low-cardinality fields and high-cardinality keys in the
// arguments take precedence over the parent's attributes.
func (s *TelemetryContext) with(
	lowCardinalityAttributes LowCardinalityAttributes,
	highCardinalityAttributes map[string]string,
) *TelemetryContext {
	low := s.lowCardinalityAttributes
	low.merge(lowCardinalityAttributes)

	high := maps.Clone(s.highCardinalityAttributes)
	maps.Copy(high, highCardinalityAttributes)

	return &TelemetryContext{
		lowCardinalityAttributes:  low,
		highCardinalityAttributes: high,
	}
}

// TelemetryRecorder handles recording telemetry events to the OpenTelemetry.
//
// Recorders form a hierarchy using `With` derives a child recorder with
// additional attributes. Child recorders share the root provider's
// OpenTelemetry providers, and therefore do not need to be shut down.
type TelemetryRecorder struct {
	root             *OpenTelemetryProxy
	telemetryContext *TelemetryContext
}

func NewTelemetryRecorder(
	root *OpenTelemetryProxy,
	telemetryContext *TelemetryContext,
) *TelemetryRecorder {
	return &TelemetryRecorder{
		root:             root,
		telemetryContext: telemetryContext,
	}
}

// With returns a derived recorder whose telemetry context inherits
// this recorder's attributes merged with the provided ones.
//
// The receiver is unchanged: attributes added to the derived recorder
// never appear on records emitted through the parent or its siblings.
func (r *TelemetryRecorder) With(
	lowCardinalityAttributes LowCardinalityAttributes,
	highCardinalityAttributes map[string]string,
) *TelemetryRecorder {
	mergedLowCardinalityAttributes := r.telemetryContext.lowCardinalityAttributes
	mergedLowCardinalityAttributes.merge(lowCardinalityAttributes)

	mergedHighCardinalityAttributes := maps.Clone(
		r.telemetryContext.highCardinalityAttributes,
	)
	maps.Copy(
		mergedHighCardinalityAttributes,
		highCardinalityAttributes,
	)
	return &TelemetryRecorder{
		root: r.root,
		telemetryContext: r.telemetryContext.with(
			mergedLowCardinalityAttributes,
			mergedHighCardinalityAttributes,
		),
	}
}

// IncrementCounterAndLogEvent increments a counter metric by 1
// with the telemetry context's low-cardinality attributes
//
// It additionally records a log record with the telemetry
// context's attributes plus the caller-supplied attributes under the same
// name
func (r *TelemetryRecorder) IncrementCounterAndLogEvent(
	ctx context.Context,
	name string,
	attributes map[string]string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if r.root == nil {
		return
	}

	mergedLowCardinalityAttributes := r.telemetryContext.lowCardinalityAttributes
	mergedLowCardinalityAttributes.merge(lowCardinalityAttributes)
	r.root.incrementCounter(ctx, name, mergedLowCardinalityAttributes)

	recordAttributes := make(map[string]string)
	maps.Copy(recordAttributes, r.telemetryContext.highCardinalityAttributes)
	maps.Copy(recordAttributes, r.telemetryContext.lowCardinalityAttributes.toMap())
	maps.Copy(recordAttributes, attributes)
	r.root.log(
		ctx,
		name,
		recordAttributes,
		otellogapi.SeverityInfo,
	)
}

// Log emits an OpenTelemetry log record with the specified severity level.
//
// The log record contains the telemetry context's attributes,
// in addition to the caller-supplied attributes
func (r *TelemetryRecorder) Log(
	ctx context.Context,
	message string,
	attributes map[string]string,
	severity otellogapi.Severity,
) {
	if r.root == nil {
		return
	}

	// Copy attributes in order of precedence:
	// 1. Context's high-cardinality attributes
	// 2. Context's low-cardinality attributes
	// 3. Per-record low-cardinality attributes
	// 4. Per-record attributes
	logAttributes := make(map[string]string)
	maps.Copy(logAttributes, r.telemetryContext.highCardinalityAttributes)
	maps.Copy(logAttributes, r.telemetryContext.lowCardinalityAttributes.toMap())
	maps.Copy(logAttributes, attributes)
	r.root.log(ctx, message, logAttributes, severity)
}

// Error records an error as both a counter metric and an error log.
//
// The counter metric has the name "error" and contains
// the low-cardinality attributes from the current telemetry context plus an
// "error.type" attribute (the caller-supplied error type) so the
// rate of each error type can be aggregated and graphed.
//
// The log record contains the attributes from the current telemetry context,
// plus "error.type", "error.message", "error.stacktrace", and
// "code.function.name". The stack trace is captured at the point Error is
// called.
//
// errorOriginator is the fully-qualified package and function name
// of the code the error is attributed to (following the OpenTelemetry
// "code.function.name" convention)
func (r *TelemetryRecorder) Error(
	ctx context.Context,
	message string,
	err error,
	errorOriginator string,
) {
	if r.root == nil {
		return
	}

	errorMessage := ""
	if err != nil {
		errorMessage = err.Error()
	}

	lowCardinalityAttributes := r.telemetryContext.lowCardinalityAttributes
	lowCardinalityAttributes.merge(LowCardinalityAttributes{
		ErrorOriginator: errorOriginator,
	})

	r.root.incrementCounter(
		ctx,
		"error",
		lowCardinalityAttributes,
	)

	logAttributes := make(map[string]string)
	maps.Copy(logAttributes, r.telemetryContext.highCardinalityAttributes)
	maps.Copy(logAttributes, lowCardinalityAttributes.toMap())
	maps.Copy(logAttributes, map[string]string{
		"error.message":    errorMessage,
		"error.stacktrace": captureStacktrace(),
	})
	r.root.log(
		ctx,
		message,
		logAttributes,
		otellogapi.SeverityError,
	)
}

// OpenTelemetryProxyImpl sends metrics, logs events through the W&B
// backend's OpenTelemetry proxy API.
type OpenTelemetryProxy struct {
	// endpoint is the URL of the OpenTelemetry proxy API.
	endpoint string

	// logProvider is the OpenTelemetry log provider.
	logProvider *otellog.LoggerProvider
	// meterProvider is the OpenTelemetry meter provider.
	meterProvider *metric.MeterProvider

	// httpClient is the HTTP client used to send metrics and logs
	// to the OpenTelemetry proxy API.
	httpClient *http.Client

	// shutdown guards Shutdown so the providers are only shut down once.
	shutdown atomic.Bool
}

// NewOpenTelemetryProxy returns an OpenTelemetryProxy for the given endpoint.
//
// When analytics is disabled or no API key is available, a no-op proxy is
// returned so no providers are created and nothing is recorded.
func NewOpenTelemetryProxy(
	ctx context.Context,
	wandbSettings *settings.Settings,
) *OpenTelemetryProxy {
	proxy := &OpenTelemetryProxy{
		endpoint:   wandbSettings.GetBaseURL(),
		httpClient: newOTLPHTTPClient(wandbSettings),
	}
	if err := proxy.initializeOTelResources(ctx); err != nil {
		return nil
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
func (o *OpenTelemetryProxy) initializeOTelResources(ctx context.Context) error {
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
	return nil
}

// setupMetrics sets up the OpenTelemetry meter provider, used to record metrics.
func (o *OpenTelemetryProxy) setupMetrics(
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
func (o *OpenTelemetryProxy) setupLogs(
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

// Shutdown flushes any pending records and shuts down all providers,
// after which this proxy and every recorder derived from it become
// no-ops.
//
// It should be called once when telemetry is no longer needed.
// Additional calls to Shutdown are no-ops.
func (o *OpenTelemetryProxy) Shutdown(ctx context.Context) error {
	if !o.shutdown.CompareAndSwap(false, true) {
		return nil
	}

	meterProvider := o.meterProvider
	logProvider := o.logProvider
	return shutdownTelemetryProviders(ctx, meterProvider, logProvider)
}

// incrementCounter increments a counter metric by 1.
func (o *OpenTelemetryProxy) incrementCounter(
	ctx context.Context,
	name string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if o.meterProvider == nil {
		return
	}

	meter := o.meterProvider.Meter(serviceName)
	counter, err := meter.Int64Counter(name)
	if err != nil {
		return
	}

	counter.Add(ctx, 1, toOTelAttrs(lowCardinalityAttributes.toMap()))
}

// log emits an OpenTelemetry log record with the supplied attributes
// and severity level.
func (o *OpenTelemetryProxy) log(
	ctx context.Context,
	body string,
	attributes map[string]string,
	severity otellogapi.Severity,
) {
	if o.logProvider == nil {
		return
	}

	logger := o.logProvider.Logger(serviceName)
	var record otellogapi.Record
	record.SetBody(otellogapi.StringValue(body))
	record.SetSeverity(severity)

	if len(attributes) > 0 {
		kvs := make([]otellogapi.KeyValue, 0, len(attributes))
		for k, v := range attributes {
			kvs = append(kvs, otellogapi.String(k, v))
		}
		record.AddAttributes(kvs...)
	}

	logger.Emit(ctx, record)
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
