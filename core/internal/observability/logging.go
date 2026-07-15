package observability

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"time"

	"github.com/getsentry/sentry-go"
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
	sentryCtx *SentryContext // nil if Sentry is disabled

	telemetryProxy analytics.TelemetryRecorder // nil if telemetry is disabled

	extraSentryTags Tags // extra Sentry tags for just this logger

	captureRateLimiter *CaptureRateLimiter
}

// NewCoreLogger returns a new logger that writes messages to the slog Logger
// and uploads captured messages using a clone of the sentryHub.
//
// sentryHub can be set to nil to disable Sentry.
func NewCoreLogger(
	logger *slog.Logger,
	sentryCtx *SentryContext,
	telemetryProxy analytics.TelemetryRecorder,
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
		sentryCtx:          sentryCtx,
		telemetryProxy:     telemetryProxy,
		extraSentryTags:    make(Tags),
		captureRateLimiter: captureRateLimiter,
	}
}

// withArgs applies the given args to the logger's base tags.
//
// Merges the given args with the logger's base tags and returns the result.
// logger's base tags take precedence over args.
func (cl *CoreLogger) withArgs(args ...any) Tags {
	tags := NewTags(args...)
	maps.Copy(tags, cl.extraSentryTags)
	return tags
}

// With returns a derived logger with additional slog attrs and Sentry tags.
//
// The returned logger inherits the attrs and tags of this logger.
//
// The additional attrs are logged with every message and included as tags on
// every Sentry event. The tags are only uploaded to Sentry, so they can
// be more verbose.
func (cl *CoreLogger) With(
	attrs []any,
	tags map[string]string,
) *CoreLogger {
	newTags := NewTags(attrs...)
	maps.Copy(newTags, tags)

	extraSentryTags := maps.Clone(cl.extraSentryTags)
	maps.Copy(extraSentryTags, newTags)

	// Derive a child telemetry context so the new attributes are attached
	// to telemetry emitted through the derived logger only.
	telemetryProxy := cl.telemetryProxy
	if telemetryProxy != nil {
		telemetryProxy = telemetryProxy.With(
			newTags,
			analytics.LowCardinalityAttributes{},
		)
	}

	return &CoreLogger{
		Logger:             cl.Logger.With(attrs...),
		sentryCtx:          cl.sentryCtx,
		telemetryProxy:     telemetryProxy,
		extraSentryTags:    extraSentryTags,
		captureRateLimiter: cl.captureRateLimiter,
	}
}

// CaptureError logs an error and sends it to Sentry.
func (cl *CoreLogger) CaptureError(
	errorOriginator string,
	err error,
	args ...any,
) {
	cl.Error(err.Error(), args...)
	cl.captureException(errorOriginator, err, args...)
}

// CaptureFatal logs a fatal error and records a corresponding telemetry event.
func (cl *CoreLogger) CaptureFatal(
	errorOriginator string,
	err error,
	args ...any,
) {
	cl.Log(context.Background(), LevelFatal, err.Error(), args...)
	cl.captureException(errorOriginator, err, args...)
}

// CaptureFatalAndPanic logs a fatal error, sends it to Sentry and panics.
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

	// Try to finish uploads to Sentry before re-panicking.
	if cl.sentryCtx != nil {
		flushed := cl.sentryCtx.Flush(2 * time.Second)

		if !flushed {
			msg := "observability: failed to flush Sentry"
			cl.Error(msg)
			slog.Error(msg)
		}
	}

	panic(err)
}

// CaptureWarn logs a warning and sends it to Sentry.
func (cl *CoreLogger) CaptureWarn(msg string, args ...any) {
	cl.Warn(msg, args...)
	cl.captureMessage(msg, otellogapi.SeverityWarn, args...)
}

// CaptureInfo logs an info message and sends it to Sentry.
func (cl *CoreLogger) CaptureInfo(msg string, args ...any) {
	cl.Info(msg, args...)
	cl.captureMessage(msg, otellogapi.SeverityInfo, args...)
}

// captureException uploads an error to Sentry if possible and allowed.
//
// codeFunctionName is the fully-qualified name of the function the error is
// attributed to, recorded as the telemetry "code.function.name" attribute.
func (cl *CoreLogger) captureException(
	errorOriginator string,
	err error,
	args ...any,
) {
	if cl.telemetryProxy != nil {
		cl.telemetryProxy.Error(
			context.Background(),
			errorOriginator,
			err.Error(),
		)
	}

	if cl.sentryCtx == nil || !cl.captureRateLimiter.AllowCapture(err.Error()) {
		return
	}

	cl.sentryCtx.WithScope(func(hub *sentry.Hub) {
		hub.Scope().SetTags(cl.withArgs(args...))
		hub.CaptureException(err)
	})
}

// captureException uploads a message to Sentry if possible and allowed.
func (cl *CoreLogger) captureMessage(
	msg string,
	severity otellogapi.Severity,
	args ...any,
) {
	if cl.telemetryProxy != nil {
		cl.telemetryProxy.RecordLog(
			context.Background(),
			msg,
			argsToAttributes(args...),
			analytics.LowCardinalityAttributes{},
			severity,
		)
	}

	if cl.sentryCtx == nil || !cl.captureRateLimiter.AllowCapture(msg) {
		return
	}

	cl.sentryCtx.WithScope(func(hub *sentry.Hub) {
		hub.Scope().SetTags(cl.withArgs(args...))
		hub.CaptureMessage(msg)
	})
}

// Reraise logs a panic, uploads it to Sentry, and re-panics.
//
// It is meant to be used in a `defer` statement.
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
	if cl.telemetryProxy == nil {
		return
	}

	cl.telemetryProxy.IncrementCounterAndLogEvent(
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
		nil,
		nil,
	)
}

func argsToAttributes(args ...any) map[string]string {
	attributes := make(map[string]string)
	for _, arg := range args {
		if attr, ok := arg.(slog.Attr); ok {
			attributes[attr.Key] = attr.Value.String()
		}
	}
	return attributes
}
