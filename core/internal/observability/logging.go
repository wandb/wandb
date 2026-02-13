package observability

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"sync"
	"time"

	"github.com/getsentry/sentry-go"
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
	mu sync.Mutex // for operations that use the Sentry hub's scope

	*slog.Logger
	sentryHub *sentry.Hub // nil if Sentry is disabled

	baseTags Tags

	captureRateLimiter *CaptureRateLimiter
}

// NewCoreLogger returns a new logger that writes messages to the slog Logger
// and uploads captured messages using a clone of the sentryHub.
//
// sentryHub can be set to nil to disable Sentry.
func NewCoreLogger(
	logger *slog.Logger,
	sentryHub *sentry.Hub,
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

	if sentryHub != nil {
		sentryHub = sentryHub.Clone()
		sentryHub.ConfigureScope(func(scope *sentry.Scope) {
			scope.AddEventProcessor(RemoveLoggerFrames)
		})
	}

	return &CoreLogger{
		Logger:             logger,
		sentryHub:          sentryHub,
		baseTags:           make(Tags),
		captureRateLimiter: captureRateLimiter,
	}
}

// withArgs applies the given args to the logger's base tags.
//
// Merges the given args with the logger's base tags and returns the result.
// logger's base tags take precedence over args.
func (cl *CoreLogger) withArgs(args ...any) Tags {
	tags := NewTags(args...)
	maps.Copy(tags, cl.baseTags)
	return tags
}

// SetGlobalTags updates tags that are shared by all loggers related to this
// one, including its parent and descendants.
//
// Note that these tags take precedence over tags set by With().
func (cl *CoreLogger) SetGlobalTags(tags Tags) {
	maps.Copy(cl.baseTags, tags)
}

// With returns a derived logger that includes the given tags in each message.
func (cl *CoreLogger) With(args ...any) *CoreLogger {
	var sentryHub *sentry.Hub
	if cl.sentryHub != nil {
		sentryHub = cl.sentryHub.Clone()
	}

	return &CoreLogger{
		Logger:             cl.Logger.With(args...),
		sentryHub:          sentryHub,
		baseTags:           cl.baseTags,
		captureRateLimiter: cl.captureRateLimiter,
	}
}

// CaptureError logs an error and sends it to Sentry.
func (cl *CoreLogger) CaptureError(err error, args ...any) {
	cl.Error(err.Error(), args...)
	cl.captureException(err, args...)
}

// CaptureFatal logs a fatal error and sends it to Sentry.
func (cl *CoreLogger) CaptureFatal(err error, args ...any) {
	cl.Log(context.Background(), LevelFatal, err.Error(), args...)
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
	slog.Log(context.Background(), LevelFatal, err.Error(), args...)

	// Try to finish uploads to Sentry before re-panicking.
	if cl.sentryHub != nil {
		flushed := cl.sentryHub.Flush(2 * time.Second)

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
	if cl.sentryHub == nil || !cl.captureRateLimiter.AllowCapture(err.Error()) {
		return
	}

	cl.mu.Lock()
	defer cl.mu.Unlock()

	cl.sentryHub.WithScope(func(scope *sentry.Scope) {
		scope.SetTags(cl.withArgs(args...))
		cl.sentryHub.CaptureException(err)
	})
}

// captureException uploads a message to Sentry if possible and allowed.
func (cl *CoreLogger) captureMessage(msg string, args ...any) {
	if cl.sentryHub == nil || !cl.captureRateLimiter.AllowCapture(msg) {
		return
	}

	cl.mu.Lock()
	defer cl.mu.Unlock()

	cl.sentryHub.WithScope(func(scope *sentry.Scope) {
		scope.SetTags(cl.withArgs(args...))
		cl.sentryHub.CaptureMessage(msg)
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

// GetTags returns the tags associated with the logger.
//
// Used for testing.
func (cl *CoreLogger) GetTags() Tags {
	return cl.baseTags
}

// NewNoOpLogger returns a logger that discards all messages.
//
// Used for testing.
func NewNoOpLogger() *CoreLogger {
	return NewCoreLogger(slog.New(slog.NewJSONHandler(io.Discard, nil)), nil)
}
