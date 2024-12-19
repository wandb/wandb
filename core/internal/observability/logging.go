package observability

import (
	"context"
	"io"
	"log/slog"

	"github.com/wandb/wandb/core/internal/sentry_ext"
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

type LoggerParams struct {
	Sentry *sentry_ext.Client
	Tags   Tags
}

type Logger struct {
	*slog.Logger
	baseTags Tags
	sentry   *sentry_ext.Client
}

func NewLogger(logger *slog.Logger, params *LoggerParams) *Logger {

	if params == nil {
		params = &LoggerParams{}
	}

	tags := Tags{}
	var args []any
	for key, value := range params.Tags {
		args = append(args, slog.String(key, value))
		tags[key] = value
	}

	return &Logger{
		Logger:   logger.With(args...),
		sentry:   params.Sentry,
		baseTags: tags,
	}
}

// withArgs applies the given args to the logger's base tags.
//
// Merges the given args with the logger's base tags and returns the result.
// logger's base tags take precedence over args.
func (cl *Logger) withArgs(args ...any) Tags {
	tags := NewTags(args...)
	// add tags from logger:
	for key, value := range cl.baseTags {
		tags[key] = value
	}
	return tags
}

// SetGlobalTags updates tags that are shared by all loggers related to this
// one, including its parent and descendants.
//
// Note that these tags take precedence over tags set by With().
func (cl *Logger) SetGlobalTags(tags Tags) {
	for key, value := range tags {
		cl.baseTags[key] = value
	}
}

// With returns a derived logger that includes the given tags in each message.
func (cl *Logger) With(args ...any) *Logger {
	return &Logger{
		Logger:   cl.Logger.With(args...),
		baseTags: cl.baseTags,
		sentry:   cl.sentry,
	}
}

// CaptureError logs an error and sends it to Sentry.
func (cl *Logger) CaptureError(err error, args ...any) {
	cl.Logger.Error(err.Error(), args...)

	if cl.sentry != nil {
		cl.sentry.CaptureException(err, cl.withArgs(args...))
	}
}

// CaptureFatal logs a fatal error and sends it to Sentry.
func (cl *Logger) CaptureFatal(err error, args ...any) {
	cl.Logger.Log(context.Background(), LevelFatal, err.Error(), args...)

	if cl.sentry != nil {
		cl.sentry.CaptureException(err, cl.withArgs(args...))
	}
}

// CaptureFatalAndPanic logs a fatal error, sends it to Sentry and panics.
func (cl *Logger) CaptureFatalAndPanic(err error, args ...any) {
	cl.CaptureFatal(err, args...)
	if err != nil {
		panic(err)
	}
}

// CaptureWarn logs a warning and sends it to Sentry.
func (cl *Logger) CaptureWarn(msg string, args ...any) {
	cl.Logger.Warn(msg, args...)

	if cl.sentry != nil {
		cl.sentry.CaptureMessage(msg, cl.withArgs(args...))
	}
}

// CaptureInfo logs an info message and sends it to Sentry.
func (cl *Logger) CaptureInfo(msg string, args ...any) {
	cl.Logger.Info(msg, args...)

	if cl.sentry != nil {
		cl.sentry.CaptureMessage(msg, cl.withArgs(args...))
	}
}

// Reraise reports panics to Sentry.
func (cl *Logger) Reraise(args ...any) {
	if err := recover(); err != nil {
		cl.sentry.Reraise(err, cl.withArgs(args...))
	}
}

// GetTags returns the tags associated with the logger.
//
// Used for testing.
func (cl *Logger) GetTags() Tags {
	return cl.baseTags
}

// GetLogger returns the underlying slog.Logger.
//
// Used for testing.
func (cl *Logger) GetSentry() *sentry_ext.Client {
	return cl.sentry
}

// NewNoOpLogger returns a logger that discards all messages.
//
// Used for testing.
func NewNoOpLogger() *Logger {
	return NewLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		nil,
	)
}
