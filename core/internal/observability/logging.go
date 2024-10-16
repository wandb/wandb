package observability

import (
	"context"
	"io"
	"log/slog"
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
	globalTags       Tags
	captureException func(err error, tags map[string]string)
	captureMessage   func(msg string, tags map[string]string)
	reraise          func(err interface{}, tags map[string]string)
}

type CoreLoggerOption func(cl *CoreLogger)

func WithCaptureMessage(f func(msg string, tags map[string]string)) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.captureMessage = f
	}
}

func WithCaptureException(f func(err error, tags map[string]string)) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.captureException = f
	}
}

func WithReraise(f func(err interface{}, tags map[string]string)) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.reraise = f
	}
}

func WithTags(tags Tags) CoreLoggerOption {
	return func(cl *CoreLogger) {
		cl.globalTags = tags
	}
}

func NewCoreLogger(logger *slog.Logger, opts ...CoreLoggerOption) *CoreLogger {

	cl := &CoreLogger{}
	for _, opt := range opts {
		opt(cl)
	}

	var args []interface{}
	for tag := range cl.globalTags {
		args = append(args, slog.String(tag, cl.globalTags[tag]))
	}
	cl.Logger = logger.With(args...)
	return cl
}

func (cl *CoreLogger) tagsWithArgs(args ...any) Tags {
	tags := NewTags(args...)
	// add tags from logger:
	for k, v := range cl.globalTags {
		tags[k] = v
	}
	return tags
}

// SetGlobalTags updates tags that are shared by all loggers related to this
// one, including its parent and descendants.
//
// Note that these tags take precedence over tags set by With().
func (cl *CoreLogger) SetGlobalTags(tags Tags) {
	for tag := range tags {
		cl.globalTags[tag] = tags[tag]
	}
}

// With returns a derived logger that includes the given tags in each message.
func (cl *CoreLogger) With(args ...any) *CoreLogger {
	return &CoreLogger{
		Logger:           cl.Logger.With(args...),
		globalTags:       cl.globalTags,
		captureException: cl.captureException,
		captureMessage:   cl.captureMessage,
		reraise:          cl.reraise,
	}
}

// CaptureError logs an error and sends it to Sentry.
func (cl *CoreLogger) CaptureError(err error, args ...any) {
	cl.Logger.Error(err.Error(), args...)

	if cl.captureException != nil {
		cl.captureException(err, cl.tagsWithArgs(args...))
	}
}

// CaptureFatal logs a fatal error and sends it to Sentry.
func (cl *CoreLogger) CaptureFatal(err error, args ...any) {
	cl.Logger.Log(context.Background(), LevelFatal, err.Error(), args...)

	if cl.captureException != nil {
		cl.captureException(err, cl.tagsWithArgs(args...))
	}
}

// CaptureFatalAndPanic logs a fatal error, sends it to Sentry and panics.
func (cl *CoreLogger) CaptureFatalAndPanic(err error, args ...any) {
	cl.CaptureFatal(err, args...)
	if err != nil {
		panic(err)
	}
}

// CaptureWarn logs a warning and sends it to Sentry.
func (cl *CoreLogger) CaptureWarn(msg string, args ...any) {
	cl.Logger.Warn(msg, args...)

	if cl.captureMessage != nil {
		cl.captureMessage(msg, cl.tagsWithArgs(args...))
	}
}

// CaptureInfo logs an info message and sends it to Sentry.
func (cl *CoreLogger) CaptureInfo(msg string, args ...any) {
	cl.Logger.Info(msg, args...)

	if cl.captureMessage != nil {
		cl.captureMessage(msg, cl.tagsWithArgs(args...))
	}
}

// Reraise reports panics to Sentry.
func (cl *CoreLogger) Reraise(args ...any) {
	if err := recover(); err != nil {
		cl.reraise(err, cl.tagsWithArgs(args...))
	}
}

// GetTags returns the tags associated with the logger.
func (cl *CoreLogger) GetTags() Tags {
	return cl.globalTags
}

// GetLogger returns the underlying slog.Logger.
func (cl *CoreLogger) GetLogger() *slog.Logger {
	return cl.Logger
}

// GetCaptureException returns the function used to capture exceptions.
func (cl *CoreLogger) GetCaptureException() func(err error, tags map[string]string) {
	return cl.captureException
}

// GetCaptureMessage returns the function used to capture messages.
func (cl *CoreLogger) GetCaptureMessage() func(msg string, tags map[string]string) {
	return cl.captureMessage
}

func NewNoOpLogger() *CoreLogger {
	return NewCoreLogger(slog.New(slog.NewJSONHandler(io.Discard, nil)),
		WithTags(Tags{}),
		WithCaptureException(func(err error, tags map[string]string) {}),
		WithCaptureMessage(func(msg string, tags map[string]string) {}),
		WithReraise(func(err interface{}, tags map[string]string) {}),
	)
}
