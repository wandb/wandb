// Package analytics provides an OpenTelemetry proxy that sends metrics, logs
// to the W&B backend's OpenTelemetry proxy API.
package analytics

import (
	"cmp"
	"context"
	"crypto/tls"
	"errors"
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
	otelmetric "go.opentelemetry.io/otel/metric"
	otellog "go.opentelemetry.io/otel/sdk/log"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	"go.opentelemetry.io/otel/sdk/resource"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"

	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
)

const (
	// defaultExportInterval is the interval at which metrics and logs are sent to the backend.
	defaultExportInterval = 60 * time.Second

	// defaultExportTimeout is the total time allowed for an export to complete.
	// It includes the time to collect and send metric/log records.
	defaultExportTimeout = 5 * time.Second

	// httpClientTimeout is the timeout for HTTP requests to the backend.
	httpClientTimeout = 10 * time.Second

	// probeTimeout is the timeout for the server capability probe.
	probeTimeout = 2 * time.Second

	metricsPath = "/sdk/otel/v1/metrics"
	logsPath    = "/sdk/otel/v1/logs"

	// unitSeconds, unitBytes and unitCount are the UCUM unit strings for the
	// histogram instruments.
	UnitSeconds      = "s"
	UnitMilliseconds = "ms"
	UnitMicroseconds = "us"
	UnitNanoseconds  = "ns"
	UnitBytes        = "By"
	UnitCount        = "1"
)

// ConfigureOTelErrorHandler routes OpenTelemetry SDK errors to the logger.
//
// Without this, the OpenTelemetry SDK prints errors to stderr, which
// corrupts the display of terminal UIs like leet.
func ConfigureOTelErrorHandler(logger *slog.Logger) {
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) {
		logger.Error(
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
	Architecture    string
	ErrorOriginator string

	PythonVersion string
	PythonRuntime string
	ExceptionType string

	// LeetMode is the leet launch mode: leet, config, inspect or symon.
	LeetMode string

	// ExecutionContext classifies where the process runs:
	// kubernetes, container, slurm, ci, ssh or local.
	ExecutionContext string
}

// merge overwrites attrs with the non-empty fields of other.
func (attrs *LowCardinalityAttributes) merge(other LowCardinalityAttributes) {
	attrs.GoVersion = cmp.Or(other.GoVersion, attrs.GoVersion)
	attrs.WandbVersion = cmp.Or(other.WandbVersion, attrs.WandbVersion)
	attrs.OperatingSystem = cmp.Or(other.OperatingSystem, attrs.OperatingSystem)
	attrs.Architecture = cmp.Or(other.Architecture, attrs.Architecture)
	attrs.ErrorOriginator = cmp.Or(other.ErrorOriginator, attrs.ErrorOriginator)

	attrs.PythonVersion = cmp.Or(other.PythonVersion, attrs.PythonVersion)
	attrs.PythonRuntime = cmp.Or(other.PythonRuntime, attrs.PythonRuntime)
	attrs.ExceptionType = cmp.Or(other.ExceptionType, attrs.ExceptionType)

	attrs.LeetMode = cmp.Or(other.LeetMode, attrs.LeetMode)
	attrs.ExecutionContext = cmp.Or(other.ExecutionContext, attrs.ExecutionContext)
}

func (attrs LowCardinalityAttributes) toMap() map[string]string {
	out := map[string]string{
		"go_version":        attrs.GoVersion,
		"operating_system":  attrs.OperatingSystem,
		"architecture":      attrs.Architecture,
		"error.originator":  attrs.ErrorOriginator,
		"python_version":    attrs.PythonVersion,
		"python_runtime":    attrs.PythonRuntime,
		"exception_type":    attrs.ExceptionType,
		"wandb_version":     attrs.WandbVersion,
		"leet_mode":         attrs.LeetMode,
		"execution_context": attrs.ExecutionContext,
	}
	maps.DeleteFunc(out, func(_ string, value string) bool {
		return value == ""
	})
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

func NewTelemetryContext() TelemetryContext {
	lowCardinalityAttributes := LowCardinalityAttributes{
		WandbVersion:    version.Version,
		GoVersion:       runtime.Version(),
		OperatingSystem: runtime.GOOS,
		Architecture:    runtime.GOARCH,
	}

	return TelemetryContext{
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
) TelemetryContext {
	low := s.lowCardinalityAttributes
	low.merge(lowCardinalityAttributes)

	high := make(map[string]string, len(s.highCardinalityAttributes))
	maps.Copy(high, s.highCardinalityAttributes)
	maps.Copy(high, highCardinalityAttributes)

	return TelemetryContext{
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
	telemetryContext TelemetryContext
}

// NewTelemetryRecorder returns a new TelemetryRecorder with the given root
// OpenTelemetryProxy and telemetry context.
//
// If the root is nil, a nil pointer is returned.
// A nil TelemetryRecorder is a no-op, as if telemetry is disabled.
func NewTelemetryRecorder(
	root *OpenTelemetryProxy,
	telemetryContext TelemetryContext,
) *TelemetryRecorder {
	if root == nil {
		return nil
	}

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
//
// If the receiver is nil, a nil pointer is returned.
// A nil TelemetryRecorder is a no-op, as if telemetry is disabled.
func (r *TelemetryRecorder) With(
	lowCardinalityAttributes LowCardinalityAttributes,
	highCardinalityAttributes map[string]string,
) *TelemetryRecorder {
	if r == nil {
		return nil
	}

	return &TelemetryRecorder{
		root: r.root,
		telemetryContext: r.telemetryContext.with(
			lowCardinalityAttributes,
			highCardinalityAttributes,
		),
	}
}

// IncrementCounter increments a counter metric by 1
// with the telemetry context's low-cardinality attributes
func (r *TelemetryRecorder) IncrementCounter(
	ctx context.Context,
	name string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	r.AddToCounter(ctx, name, 1, lowCardinalityAttributes)
}

// AddCounter increases a counter metric by delta with the telemetry
// context's low-cardinality attributes.
func (r *TelemetryRecorder) AddToCounter(
	ctx context.Context,
	name string,
	delta int64,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if r == nil {
		return
	}

	mergedLowCardinalityAttributes := r.telemetryContext.lowCardinalityAttributes
	mergedLowCardinalityAttributes.merge(lowCardinalityAttributes)
	r.root.addToCounter(ctx, name, delta, mergedLowCardinalityAttributes)
}

// DefineHistogram creates the histogram instrument named `name`, with the
// given `unit`, `description` and `boundaries`.
//
// Define each `name` once, before the first record call. If this is called
// again for the same `name`, it returns an error.
func (r *TelemetryRecorder) DefineHistogram(
	name string,
	unit string,
	description string,
	boundaries []float64,
) error {
	if r == nil {
		return nil
	}

	switch {
	case name == "":
		return errors.New("analytics: histogram with no name")
	case unit == "":
		return fmt.Errorf("analytics: %q has no unit", name)
	case len(boundaries) == 0:
		return fmt.Errorf("analytics: %q has no boundaries", name)
	}

	for i, boundary := range boundaries[1:] {
		if boundaries[i] >= boundary {
			return fmt.Errorf(
				"analytics: %q boundaries are not increasing: %v",
				name,
				boundaries,
			)
		}
	}

	return r.root.defineHistogram(name, unit, description, boundaries)
}

// RecordHistogram records a value on the histogram named name, with the
// telemetry context's low-cardinality attributes.
//
// Returns an error if the histogram is not defined.
func (r *TelemetryRecorder) RecordHistogram(
	ctx context.Context,
	name string,
	value float64,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if r == nil {
		return
	}

	mergedLowCardinalityAttributes := r.telemetryContext.lowCardinalityAttributes
	mergedLowCardinalityAttributes.merge(lowCardinalityAttributes)

	err := r.root.recordHistogram(
		ctx,
		name,
		value,
		mergedLowCardinalityAttributes,
	)
	if err != nil {
		slog.Debug("analytics: failed to record histogram", "error", err)
		return
	}
}

// IncrementCounterAndLogEvent increments a counter metric by 1
// and a log record.
//
// Equivalent to:
//
//	r.AddToCounterAndLogEvent(ctx, name, 1, attributes, lowCardinalityAttributes)
func (r *TelemetryRecorder) IncrementCounterAndLogEvent(
	ctx context.Context,
	name string,
	attributes map[string]string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	r.AddToCounterAndLogEvent(ctx, name, 1, attributes, lowCardinalityAttributes)
}

// AddToCounterAndLogEvent adds specified amount to a counter metric and
// records a log record with the same name.
//
// It includes the telemetry context's attributes plus the caller-supplied
// attributes. Low-cardinality attributes are included with the metric, and
// all attributes are included with the log record.
func (r *TelemetryRecorder) AddToCounterAndLogEvent(
	ctx context.Context,
	name string,
	delta int64,
	attributes map[string]string,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if r == nil {
		return
	}

	r.AddToCounter(ctx, name, delta, lowCardinalityAttributes)

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
	if r == nil {
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

// ErrorMetric records an error as a counter metric.
//
// The counter metric has the name "error" and contains
// the low-cardinality attributes from the current telemetry context plus an
// "error.type" attribute (the caller-supplied error type) so the
// rate of each error type can be aggregated and graphed.
func (r *TelemetryRecorder) ErrorMetric(
	ctx context.Context,
	message string,
	err error,
	errorOriginator string,
) {
	if r == nil {
		return
	}

	r.IncrementCounter(
		ctx,
		"error",
		LowCardinalityAttributes{
			ErrorOriginator: errorOriginator,
		},
	)
}

// ErrorLog emits an OpenTelemetry log record with the specified severity level.
//
// The log record contains the attributes from the current telemetry context,
// plus "error.type", "error.message", "error.stacktrace", "error.originator",
// and the caller-supplied attributes.
//
// The stack trace is captured at the point Error is called.
func (r *TelemetryRecorder) ErrorLog(
	ctx context.Context,
	message string,
	err error,
	errorOriginator string,
	attributes map[string]string,
) {
	if r == nil {
		return
	}

	mergedLowCardinalityAttributes := r.telemetryContext.lowCardinalityAttributes
	mergedLowCardinalityAttributes.merge(LowCardinalityAttributes{
		ErrorOriginator: errorOriginator,
	})

	errorMessage := ""
	if err != nil {
		errorMessage = err.Error()
	}
	logAttributes := make(map[string]string)
	maps.Copy(logAttributes, r.telemetryContext.highCardinalityAttributes)
	maps.Copy(logAttributes, mergedLowCardinalityAttributes.toMap())
	maps.Copy(logAttributes, attributes)
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

	// serviceName is the name of the service being monitored.
	// This is used to identify the service in the OpenTelemetry backend.
	serviceName string

	// serverSupported reports whether the server exposes the proxy API,
	// probing it on the first call. The exporters drop every batch when
	// it is false.
	serverSupported func() bool

	// shutdown guards Shutdown so the providers are only shut down once.
	shutdown atomic.Bool

	// counters cache resolved counter instruments.
	counters sync.Map
	// histograms cache resolved histogram instruments.
	histograms sync.Map
}

// NewOpenTelemetryProxy returns an OpenTelemetryProxy for the given endpoint.
//
// When analytics is disabled or the wandbSettings are offline, a nil pointer
// is returned, making calls to the proxy a no-op.
//
// The server is probed for the proxy API on the first export, off the
// recording goroutine; telemetry bound for a server without it is dropped.
func NewOpenTelemetryProxy(
	ctx context.Context,
	wandbSettings *settings.Settings,
	serviceName string,
) *OpenTelemetryProxy {
	if disabled.Load() || wandbSettings.IsOffline() {
		return nil
	}

	httpClient, err := newOTLPHTTPClient(wandbSettings)
	if err != nil {
		slog.Debug(
			"analytics: failed to configure telemetry authentication",
			"error", err,
		)
		return nil
	}

	proxy := &OpenTelemetryProxy{
		endpoint:    wandbSettings.GetBaseURL(),
		httpClient:  httpClient,
		serviceName: serviceName,
	}
	proxy.serverSupported = sync.OnceValue(proxy.probeServer)
	if err := proxy.initializeOTelResources(ctx); err != nil {
		return nil
	}
	return proxy
}

// probeServer reports whether the server exposes the proxy API.
func (o *OpenTelemetryProxy) probeServer() bool {
	ctx, cancel := context.WithTimeout(context.Background(), probeTimeout)
	defer cancel()
	if !checkServerSupportsOpenTelemetryProxy(ctx, o.httpClient, o.endpoint) {
		slog.Debug(
			"analytics: server does not support OpenTelemetry proxy, disabling telemetry",
		)
		return false
	}
	return true
}

// newOTLPHTTPClient builds the HTTP client used for OTLP exports.
//
// The backend accepts unauthenticated telemetry uploads, so when no
// credentials are configured the requests are simply sent without an
// Authorization header.
func newOTLPHTTPClient(
	wandbSettings *settings.Settings,
) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = wandbSettings.GetProxyFn()
	transport.ProxyConnectHeader = wandbSettings.GetProxyConnectHeader()
	if wandbSettings.IsInsecureDisableSSL() {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	extraHeaders := wandbSettings.GetExtraHTTPHeaders()

	client := &http.Client{
		Timeout: httpClientTimeout,
	}
	client.Transport = httplayers.WrapRoundTripper(
		transport,
		httplayers.Concat(
			httplayers.DefaultHeaders(extraHeaders),
		),
	)
	return client, nil
}

// initializeOTelResources initializes the OpenTelemetry meter and log providers.
func (o *OpenTelemetryProxy) initializeOTelResources(
	ctx context.Context,
) error {
	if o == nil {
		return nil
	}

	res, err := resource.New(
		ctx,
		resource.WithAttributes(semconv.ServiceName(o.serviceName)),
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
	if o == nil {
		return nil, fmt.Errorf("OpenTelemetryProxy is nil")
	}

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
			metric.NewPeriodicReader(
				probedMetricExporter{exporter, o.serverSupported},
				metric.WithInterval(defaultExportInterval),
				metric.WithTimeout(defaultExportTimeout),
			),
		),
	), nil
}

// probedMetricExporter drops exports bound for a server without the proxy API.
type probedMetricExporter struct {
	metric.Exporter
	serverSupported func() bool
}

func (e probedMetricExporter) Export(
	ctx context.Context,
	rm *metricdata.ResourceMetrics,
) error {
	if !e.serverSupported() {
		return nil
	}
	return e.Exporter.Export(ctx, rm)
}

// setupLogs sets up the OpenTelemetry log provider, used to record logs.
func (o *OpenTelemetryProxy) setupLogs(
	ctx context.Context,
	res *resource.Resource,
) (*otellog.LoggerProvider, error) {
	if o == nil {
		return nil, fmt.Errorf("OpenTelemetryProxy is nil")
	}

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
		otellog.WithProcessor(
			otellog.NewBatchProcessor(
				probedLogExporter{exporter, o.serverSupported},
				otellog.WithExportInterval(defaultExportInterval),
				otellog.WithExportTimeout(defaultExportTimeout),
			),
		),
	), nil
}

// probedLogExporter drops exports bound for a server without the proxy API.
type probedLogExporter struct {
	otellog.Exporter
	serverSupported func() bool
}

func (e probedLogExporter) Export(
	ctx context.Context,
	records []otellog.Record,
) error {
	if !e.serverSupported() {
		return nil
	}
	return e.Exporter.Export(ctx, records)
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
	if o == nil || !o.shutdown.CompareAndSwap(false, true) {
		return nil
	}

	return shutdownTelemetryProviders(ctx, o.meterProvider, o.logProvider)
}

// counter returns the counter instrument for name, resolving it once.
//
// The second return value is false if the instrument could not be created,
// in which case the caller drops the measurement.
func (o *OpenTelemetryProxy) counter(name string) (otelmetric.Int64Counter, bool) {
	if cached, ok := o.counters.Load(name); ok {
		return cached.(otelmetric.Int64Counter), true
	}

	counter, err := o.meterProvider.Meter(o.serviceName).Int64Counter(name)
	if err != nil {
		return nil, false
	}

	cached, _ := o.counters.LoadOrStore(name, counter)
	return cached.(otelmetric.Int64Counter), true
}

type histogramCacheEntry struct {
	histogram otelmetric.Float64Histogram
	unit      string
}

func (o *OpenTelemetryProxy) defineHistogram(
	name string,
	unit string,
	description string,
	boundaries []float64,
) error {
	if o == nil {
		return nil
	}

	if _, defined := o.histograms.Load(name); defined {
		return fmt.Errorf("analytics: %q is already defined", name)
	}

	histogram, err := o.meterProvider.Meter(o.serviceName).Float64Histogram(
		name,
		otelmetric.WithUnit(unit),
		otelmetric.WithDescription(description),
		otelmetric.WithExplicitBucketBoundaries(boundaries...),
	)
	if err != nil {
		return fmt.Errorf("analytics: defining %q: %w", name, err)
	}

	o.histograms.Store(name, histogramCacheEntry{histogram, unit})
	return nil
}

// histogram returns the instrument for name and unit, or nil if it does not
// exist.
func (o *OpenTelemetryProxy) histogram(
	name string,
) (otelmetric.Float64Histogram, string, bool) {
	if cached, ok := o.histograms.Load(name); ok {
		return cached.(histogramCacheEntry).histogram, cached.(histogramCacheEntry).unit, true
	}

	return nil, "", false
}

// addCounter increases a counter metric by delta.
func (o *OpenTelemetryProxy) addToCounter(
	ctx context.Context,
	name string,
	delta int64,
	lowCardinalityAttributes LowCardinalityAttributes,
) {
	if o == nil {
		return
	}

	counter, ok := o.counter(name)
	if !ok {
		return
	}

	counter.Add(ctx, delta, toOTelAttrs(lowCardinalityAttributes.toMap()))
}

// recordHistogram records a value on the histogram named name.
func (o *OpenTelemetryProxy) recordHistogram(
	ctx context.Context,
	name string,
	value float64,
	lowCardinalityAttributes LowCardinalityAttributes,
) error {
	if o == nil {
		return nil
	}

	histogram, _, ok := o.histogram(name)
	if !ok {
		return fmt.Errorf("analytics: %q is not defined", name)
	}

	histogram.Record(
		ctx,
		value,
		toOTelAttrs(lowCardinalityAttributes.toMap()),
	)
	return nil
}

// log emits an OpenTelemetry log record with the supplied attributes
// and severity level.
func (o *OpenTelemetryProxy) log(
	ctx context.Context,
	body string,
	attributes map[string]string,
	severity otellogapi.Severity,
) {
	if o == nil {
		return
	}

	logger := o.logProvider.Logger(o.serviceName)
	var record otellogapi.Record
	record.SetBody(attribute.StringValue(body))
	record.SetSeverity(severity)

	if len(attributes) > 0 {
		kvs := make([]attribute.KeyValue, 0, len(attributes))
		for k, v := range attributes {
			kvs = append(kvs, attribute.String(k, v))
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

// checkServerSupportsOpenTelemetryProxy probes the W&B OpenTelemetry proxy
// endpoint to determine whether the server exposes it.
func checkServerSupportsOpenTelemetryProxy(
	ctx context.Context,
	httpClient *http.Client,
	endpoint string,
) bool {
	url := endpoint + metricsPath
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		url,
		http.NoBody,
	)
	if err != nil {
		return false
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	// Depending on the server configuration, it may respond with a
	// 404 Not Found or a 405 Method Not Allowed when it does not support
	// the proxy API.
	return resp.StatusCode != http.StatusMethodNotAllowed &&
		resp.StatusCode != http.StatusNotFound
}
