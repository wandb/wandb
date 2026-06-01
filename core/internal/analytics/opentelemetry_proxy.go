// Package analytics provides an OpenTelemetry proxy that sends metrics, logs,
// and Segment events to the W&B backend.
package analytics

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
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
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	"go.opentelemetry.io/otel/sdk/resource"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

const (
	// TODO: make this configurable, pick up by settings
	defaultEndpoint          = "api.wandb.test"
	defaultExportIntervalMs  = 500
	defaultSegmentTimeoutSec = 5
	serviceName              = "wandb-core"
)

// OpenTelemetryProxy sends metrics, logs, and Segment events through the W&B
// backend's /sdk/ endpoints.
type OpenTelemetryProxy struct {
	endpoint string

	meterProvider *metric.MeterProvider
	logProvider   *otellog.LoggerProvider
	httpClient    *http.Client

	mu       sync.Mutex
	shutdown bool
}

func NewOpenTelemetryProxy() *OpenTelemetryProxy {
	o := &OpenTelemetryProxy{
		endpoint: defaultEndpoint,
		httpClient: &http.Client{
			Timeout: defaultSegmentTimeoutSec * time.Second,
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{
					InsecureSkipVerify: true, //nolint:gosec
				},
			},
		},
	}
	return o
}

// Start initializes the OTel meter and log providers. Must be called before
// recording events.
func (o *OpenTelemetryProxy) Start(ctx context.Context) error {
	o.mu.Lock()
	defer o.mu.Unlock()

	res, err := resource.New(ctx,
		resource.WithAttributes(semconv.ServiceName("wandb-core")),
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

func (o *OpenTelemetryProxy) setupMetrics(ctx context.Context, res *resource.Resource) error {
	exporter, err := otlpmetrichttp.New(ctx,
		otlpmetrichttp.WithEndpoint(o.endpoint),
		otlpmetrichttp.WithURLPath("/sdk/otel/v1/metrics"),
		otlpmetrichttp.WithTemporalitySelector(deltaTemporality),
		otlpmetrichttp.WithTLSClientConfig(&tls.Config{
			InsecureSkipVerify: true, //nolint:gosec
		}),
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

func (o *OpenTelemetryProxy) setupLogs(ctx context.Context, res *resource.Resource) error {
	exporter, err := otlploghttp.New(ctx,
		otlploghttp.WithEndpoint(o.endpoint),
		otlploghttp.WithURLPath("/sdk/otel/v1/logs"),
		otlploghttp.WithTLSClientConfig(&tls.Config{
			InsecureSkipVerify: true, //nolint:gosec
		}),
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

// Shutdown flushes and shuts down all providers.
func (o *OpenTelemetryProxy) Shutdown(ctx context.Context) error {
	o.mu.Lock()
	o.shutdown = true
	o.mu.Unlock()

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

// RecordEvent increments a counter metric by 1.
func (o *OpenTelemetryProxy) RecordEvent(
	name string,
	attributes map[string]string,
) {
	meter := otel.Meter(serviceName)
	counter, err := meter.Int64Counter(name)
	if err != nil {
		return
	}
	counter.Add(context.Background(), 1, toOTelAttrs(attributes))
}

// RecordValue records a float64 value on a histogram.
func (o *OpenTelemetryProxy) RecordValue(
	name string,
	value float64,
	attributes map[string]string,
) {
	meter := otel.Meter(serviceName)
	histogram, err := meter.Float64Histogram(name)
	if err != nil {
		return
	}
	histogram.Record(context.Background(), value, toOTelAttrs(attributes))
}

// RecordLog emits an OTel log record with high-cardinality attributes.
func (o *OpenTelemetryProxy) RecordLog(
	body string,
	attributes map[string]string,
	severity otellogapi.Severity,
) {
	logger := global.GetLoggerProvider().Logger(serviceName)
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

	logger.Emit(context.Background(), record)
}

func (o *OpenTelemetryProxy) RecordTelemetry(
	event string,
	attributes map[string]string,
) {
	o.RecordEvent(event, nil)
	o.RecordLog(event, attributes, otellogapi.SeverityInfo)
}

// SegmentTrack sends a Segment track event through the W&B backend proxy.
func (o *OpenTelemetryProxy) SegmentTrack(
	ctx context.Context,
	event string,
	userID string,
	properties map[string]any,
) error {
	payload := map[string]any{
		"event":  event,
		"userId": userID,
	}
	if properties != nil {
		payload["properties"] = properties
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal segment track: %w", err)
	}

	url := "https://" + o.endpoint + "/sdk/segment/v1/track"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := o.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("segment track request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("segment track returned %d", resp.StatusCode)
	}
	return nil
}

func deltaTemporality(_ metric.InstrumentKind) metricdata.Temporality {
	return metricdata.DeltaTemporality
}

func toOTelAttrs(attrs map[string]string) otelmetric.MeasurementOption {
	kvs := make([]attribute.KeyValue, 0, len(attrs))
	for k, v := range attrs {
		kvs = append(kvs, attribute.String(k, v))
	}
	return otelmetric.WithAttributes(kvs...)
}
