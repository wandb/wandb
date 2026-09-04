package observability

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"time"

	otellogapi "go.opentelemetry.io/otel/log"

	"github.com/wandb/wandb/core/internal/analytics"
)

type Tags map[string]string

// NewTags creates a new Tags from a mix of slog.Attr and a string and its
// corresponding value. It ignores incomplete pairs and other types.
func NewTags(args ...any) Tags {
	var done bool
	tags := Tags{}
	// add tags from args:
	for len(args) > 0 && !done {
		switch x := args[0].(type) {
		case slog.Attr:
			tags[x.Key] = x.Value.String()
			args = args[1:]
		case string:
			if len(args) < 2 {
				done = true
				break
			}
			attr := slog.Any(x, args[1])
			tags[attr.Key] = attr.Value.String()
			args = args[2:]
		default:
			args = args[1:]
		}
	}
	return tags
}

const LevelFatal = slog.Level(12)

type CoreLogger struct {
	*slog.Logger

	TelemetryRecorder *analytics.TelemetryRecorder

	// extraTags holds tags that apply to this logger only (set via With).
	extraTags Tags

	captureRateLimiter *CaptureRateLimiter
}

// NewCoreLogger returns a new logger that writes messages to the slog Logger
// and uploads captured messages to Datadog.
func NewCoreLogger(
	logger *slog.Logger,
	telemetryRecorder *analytics.TelemetryRecorder,
) *CoreLogger {
	const captureRateLimiterCacheSize = 100
	const captureMinDuration = 5 * time.Minute
	captureRateLimiter, err := NewCaptureRateLimiter(
		captureRateLimiterCacheSize,
		captureMinDuration,
	)

	if err != nil {
		// Shouldn't happen. If it does, a nil captureRateLimiter will be
		// used (and won't panic).
		logger.Error(fmt.Sprintf(
			"observability: couldn't make CaptureRateLimiter: %v", err))
	}

	return &CoreLogger{
		Logger:             logger,
		TelemetryRecorder:  telemetryRecorder,
		extraTags:          make(Tags),
		captureRateLimiter: captureRateLimiter,
	}
}

// withArgs applies the given args to the logger's base tags.
//
// Merges the given args with the logger's base tags and returns the result.
// logger's base tags take precedence over args.
func (cl *CoreLogger) withArgs(args ...any) Tags {
	tags := NewTags(args...)
	maps.Copy(tags, cl.extraTags)
	return tags
}

// With returns a derived logger with additional slog attrs and telemetry tags.
//
// The returned logger inherits the attrs and tags of this logger.
//
// The additional attrs are logged with every message and included as tags on
// every OpenTelemetry event.
func (cl *CoreLogger) With(
	attrs []any,
	tags map[string]string,
) *CoreLogger {
	newTags := NewTags(attrs...)
	maps.Copy(newTags, tags)

	extraTags := maps.Clone(cl.extraTags)
	maps.Copy(extraTags, newTags)

	// Derive a child telemetry context so the new attributes are attached
	// to telemetry emitted through the derived logger only.
	telemetryRecorder := cl.TelemetryRecorder.With(
		analytics.LowCardinalityAttributes{},
		map[string]string(newTags),
	)

	return &CoreLogger{
		Logger:             cl.Logger.With(attrs...),
		TelemetryRecorder:  telemetryRecorder,
		extraTags:          extraTags,
		captureRateLimiter: cl.captureRateLimiter,
	}
}

// CaptureError logs an error and records a corresponding telemetry event.
//
// errorOriginator must be the declared package name of the calling file.
func (cl *CoreLogger) CaptureError(
	errorOriginator string,
	err error,
	args ...any,
) {
	cl.Error(err.Error(), args...)
	cl.captureException(errorOriginator, err, args...)
}

// CaptureFatal logs a fatal error and records a corresponding telemetry event.
//
// errorOriginator must be the declared package name of the calling file.
func (cl *CoreLogger) CaptureFatal(
	errorOriginator string,
	err error,
	args ...any,
) {
	cl.Log(context.Background(), LevelFatal, err.Error(), args...)
	cl.captureException(errorOriginator, err, args...)
}

// CaptureFatalAndPanic logs a fatal error, records a corresponding telemetry
// event, and panics.
//
// errorOriginator must be the declared package name of the calling file.
func (cl *CoreLogger) CaptureFatalAndPanic(
	errorOriginator string,
	err error,
	args ...any,
) {
	if err == nil {
		err = errors.New("observability: panicked with nil error")
	}

	cl.CaptureFatal(errorOriginator, err, args...)

	// Log panics to debug-core.log as well. This helps debugging if there are
	// multiple active debug files.
	slog.Log(context.Background(), LevelFatal, err.Error(), args...)

	panic(err)
}

// CaptureWarn logs a warning and records a corresponding telemetry event.
func (cl *CoreLogger) CaptureWarn(msg string, args ...any) {
	cl.Warn(msg, args...)
	cl.captureMessage(msg, otellogapi.SeverityWarn, args...)
}

// CaptureInfo logs an info message and records a corresponding telemetry event.
func (cl *CoreLogger) CaptureInfo(msg string, args ...any) {
	cl.Info(msg, args...)
	cl.captureMessage(msg, otellogapi.SeverityInfo, args...)
}

// captureException captures a telemetry error event if possible and allowed.
//
// errorOriginator is a telemetry tag that attributes where the
// error was captured.
func (cl *CoreLogger) captureException(
	errorOriginator string,
	err error,
	args ...any,
) {
	// Always record the error as a counter metric.
	// Since it will allow us to still see all errors,
	// without flooding our logs.
	cl.TelemetryRecorder.ErrorMetric(
		context.Background(),
		err.Error(),
		err,
		errorOriginator,
	)

	if !cl.captureRateLimiter.AllowCapture(err.Error()) {
		return
	}

	cl.TelemetryRecorder.ErrorLog(
		context.Background(),
		err.Error(),
		err,
		errorOriginator,
		cl.withArgs(args...),
	)

}

// captureMessage captures a telemetry event if possible and allowed.
func (cl *CoreLogger) captureMessage(
	msg string,
	severity otellogapi.Severity,
	args ...any,
) {
	if !cl.captureRateLimiter.AllowCapture(msg) {
		return
	}

	cl.TelemetryRecorder.Log(
		context.Background(),
		msg,
		NewTags(args...),
		severity,
	)

}

// Reraise logs a panic, records a telemetry error event, and re-panics.
//
// It is meant to be used in a `defer` statement.
// errorOriginator must be the declared package name of the calling file.
func (cl *CoreLogger) Reraise(errorOriginator string, args ...any) {
	panicErr := recover()
	if panicErr == nil { // if NO error, return
		return
	}

	if err, ok := panicErr.(error); ok {
		cl.CaptureFatalAndPanic(errorOriginator, err, args...)
	} else {
		cl.CaptureFatalAndPanic(
			errorOriginator,
			fmt.Errorf("%v", panicErr),
			args...,
		)
	}
}

// RecordTelemetry records an event as both a counter metric and a log record.
//
// The counter metric aggregates over a low-cardinality attribute space, while
// the log record captures the full, possibly high-cardinality, attributes.
func (cl *CoreLogger) RecordTelemetry(
	event string,
	attributes map[string]string,
) {
	cl.TelemetryRecorder.IncrementCounterAndLogEvent(
		context.Background(),
		event,
		attributes,
		analytics.LowCardinalityAttributes{},
	)
}

// NewNoOpLogger returns a logger that discards all messages.
//
// Used for testing.
func NewNoOpLogger() *CoreLogger {
	return NewCoreLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		analytics.NewTelemetryRecorder(nil, analytics.NewTelemetryContext()),
	)
}
