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

	"github.com/wandb/wandb/core/internal/observability/wberrors"
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
	extraSentryTags := maps.Clone(cl.extraSentryTags)
	maps.Copy(extraSentryTags, NewTags(attrs...))
	maps.Copy(extraSentryTags, tags)

	return &CoreLogger{
		Logger:             cl.Logger.With(attrs...),
		sentryCtx:          cl.sentryCtx,
		extraSentryTags:    extraSentryTags,
		captureRateLimiter: cl.captureRateLimiter,
	}
}

// withErrorAttrs appends any wberrors attrs from the error to the slog args.
func withErrorAttrs(err error, args []any) []any {
	attrs := wberrors.Attrs(err)
	if len(attrs) == 0 {
		return args
	}

	result := make([]any, len(args), len(args)+len(attrs))
	copy(result, args)
	for _, attr := range attrs {
		result = append(result, attr)
	}
	return result
}

// CaptureError logs an error and sends it to Sentry.
func (cl *CoreLogger) CaptureError(err error, args ...any) {
	cl.Error(err.Error(), withErrorAttrs(err, args)...)
	cl.captureException(err, args...)
}

// CaptureFatal logs a fatal error and sends it to Sentry.
func (cl *CoreLogger) CaptureFatal(err error, args ...any) {
	cl.Log(
		context.Background(), LevelFatal, err.Error(),
		withErrorAttrs(err, args)...,
	)
	cl.captureException(err, args...)
}

// CaptureFatalAndPanic logs a fatal error, sends it to Sentry and panics.
func (cl *CoreLogger) CaptureFatalAndPanic(err error, args ...any) {
	if err == nil {
		err = errors.New("observability: panicked with nil error")
	}

	cl.CaptureFatal(err, args...)

	// Log panics to debug-core.log as well. This helps debugging if there are
	// multiple active debug files.
	slog.Log(
		context.Background(), LevelFatal, err.Error(),
		withErrorAttrs(err, args)...,
	)

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
	cl.captureMessage(msg, args...)
}

// CaptureInfo logs an info message and sends it to Sentry.
func (cl *CoreLogger) CaptureInfo(msg string, args ...any) {
	cl.Info(msg, args...)
	cl.captureMessage(msg, args...)
}

// captureException uploads an error to Sentry if possible and allowed.
func (cl *CoreLogger) captureException(err error, args ...any) {
	if cl.sentryCtx == nil ||
		wberrors.SkipSentry(err) ||
		!cl.captureRateLimiter.AllowCapture(err.Error()) {
		return
	}

	cl.sentryCtx.WithScope(func(hub *sentry.Hub) {
		hub.Scope().SetTags(cl.withArgs(args...))
		hub.Scope().SetTags(wberrors.Tags(err))

		if fp := wberrors.ExtraFingerprint(err); len(fp) > 0 {
			hub.Scope().SetFingerprint(
				append([]string{"{{ default }}"}, fp...),
			)
		}

		hub.CaptureException(err)
	})
}

// captureException uploads a message to Sentry if possible and allowed.
func (cl *CoreLogger) captureMessage(msg string, args ...any) {
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
func (cl *CoreLogger) Reraise(args ...any) {
	panicErr := recover()
	if panicErr == nil { // if NO error, return
		return
	}

	if err, ok := panicErr.(error); ok {
		cl.CaptureFatalAndPanic(err, args...)
	} else {
		cl.CaptureFatalAndPanic(fmt.Errorf("%v", panicErr), args...)
	}
}

// NewNoOpLogger returns a logger that discards all messages.
//
// Used for testing.
func NewNoOpLogger() *CoreLogger {
	return NewCoreLogger(slog.New(slog.NewJSONHandler(io.Discard, nil)), nil)
}
