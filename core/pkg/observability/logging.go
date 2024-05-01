package observability

import (
	"context"
	"io"
	"log/slog"
)

type Tags map[string]string

// NewTags creates a new Tags from a mix of slog.Attr and a string and its corresponding value.
// It ignores incomplete pairs and other types.
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
	tags             Tags
	captureException func(err error, tags Tags)
	captureMessage   func(msg string, tags Tags)
}

type CoreLoggerOption func(cl *CoreLogger)

func WithCaptureMessage(f func(msg string, tags Tags)) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.captureMessage = f
	}
}

func WithCaptureException(f func(err error, tags Tags)) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.captureException = f
	}
}

func WithTags(tags Tags) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.tags = tags
	}
}

func NewCoreLogger(logger *slog.Logger, opts ...CoreLoggerOption) *CoreLogger {

	cl := &CoreLogger{}
	for _, opt := range opts {
		opt(cl)
	}

	var args []interface{}
	for tag := range cl.tags {
		args = append(args, slog.String(tag, cl.tags[tag]))
	}
	cl.Logger = logger.With(args...)
	return cl
}

func (cl *CoreLogger) tagsWithArgs(args ...any) Tags {
	tags := NewTags(args...)
	// add tags from logger:
	for k, v := range cl.tags {
		tags[k] = v
	}
	return tags
}

func (cl *CoreLogger) SetTags(tags Tags) {
	for tag := range tags {
		cl.tags[tag] = tags[tag]
	}
}

// CaptureError logs an error and sends it to sentry.
func (cl *CoreLogger) CaptureError(msg string, err error, args ...any) {
	args = append(args, "error", err)
	cl.Logger.Error(msg, args...)
	if err != nil {
		// send error to sentry:
		if cl.captureException != nil {
			// convert args to tags to pass to sentry:
			tags := cl.tagsWithArgs(args...)
			cl.captureException(err, tags)
		}
	}
}

// Fatal logs an error at the fatal level.
func (cl *CoreLogger) Fatal(msg string, err error, args ...any) {
	args = append(args, "error", err)
	cl.Logger.Log(context.TODO(), LevelFatal, msg, args...)
}

// FatalAndPanic logs an error at the fatal level and panics.
func (cl *CoreLogger) FatalAndPanic(msg string, err error, args ...any) {
	cl.Fatal(msg, err, args...)
	if err != nil {
		panic(err)
	}
}

// CaptureFatal logs an error at the fatal level and sends it to sentry.
func (cl *CoreLogger) CaptureFatal(msg string, err error, args ...any) {
	// TODO: make sure this level is printed nicely
	args = append(args, "error", err)
	cl.Logger.Log(context.TODO(), LevelFatal, msg, args...)
	if err != nil {
		// send error to sentry:
		if cl.captureException != nil {
			// convert args to tags to pass to sentry:
			tags := cl.tagsWithArgs(args...)
			cl.captureException(err, tags)
		}
	}
}

// CaptureFatalAndPanic logs an error at the fatal level and sends it to sentry.
// It then panics.
func (cl *CoreLogger) CaptureFatalAndPanic(msg string, err error, args ...any) {
	cl.CaptureFatal(msg, err, args...)
	if err != nil {
		panic(err)
	}
}

// CaptureWarn logs a warning and sends it to sentry.
func (cl *CoreLogger) CaptureWarn(msg string, args ...any) {
	cl.Logger.Warn(msg, args...)
	// send message to sentry:
	if cl.captureMessage != nil {
		tags := cl.tagsWithArgs(args...)
		cl.captureMessage(msg, tags)
	}
}

// CaptureInfo logs an info message and sends it to sentry.
func (cl *CoreLogger) CaptureInfo(msg string, args ...any) {
	cl.Logger.Info(msg, args...)
	// send message to sentry:
	if cl.captureMessage != nil {
		tags := cl.tagsWithArgs(args...)
		cl.captureMessage(msg, tags)
	}
}

// Reraise is used to capture unexpected panics with sentry and reraise them.
func (cl *CoreLogger) Reraise(args ...any) {
	if err := recover(); err != nil {
		Reraise(err, cl.tagsWithArgs(args...))
	}
}

// GetTags returns the tags associated with the logger.
func (cl *CoreLogger) GetTags() Tags {
	return cl.tags
}

// GetLogger returns the underlying slog.Logger.
func (cl *CoreLogger) GetLogger() *slog.Logger {
	return cl.Logger
}

// GetCaptureException returns the function used to capture exceptions.
func (cl *CoreLogger) GetCaptureException() func(err error, tags Tags) {
	return cl.captureException
}

// GetCaptureMessage returns the function used to capture messages.
func (cl *CoreLogger) GetCaptureMessage() func(msg string, tags Tags) {
	return cl.captureMessage
}

func NewNoOpLogger() *CoreLogger {
	return NewCoreLogger(slog.New(slog.NewJSONHandler(io.Discard, nil)),
		WithTags(Tags{}),
		WithCaptureException(func(err error, tags Tags) {}),
		WithCaptureMessage(func(msg string, tags Tags) {}),
	)
}
