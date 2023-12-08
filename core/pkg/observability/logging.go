package observability

import (
	"context"
	"io"
	"log/slog"
)

type Tags map[string]string

const LevelFatal = slog.Level(12)

type CoreLogger struct {
	*slog.Logger
	tags Tags
}

func NewCoreLogger(logger *slog.Logger, tags Tags) *CoreLogger {
	if tags == nil {
		tags = make(Tags)
	}
	nl := &CoreLogger{
		tags: tags,
	}

	var args []interface{}
	for tag := range nl.tags {
		args = append(args, slog.String(tag, nl.tags[tag]))
	}
	nl.Logger = logger.With(args...)

	return nl
}

func (nl *CoreLogger) tagsFromArgs(args ...any) Tags {
	tags := make(map[string]string)
	// add tags from args:
	for len(args) > 0 {
		switch x := args[0].(type) {
		case slog.Attr:
			tags[x.Key] = x.Value.String()
			args = args[1:]
		case string:
			if len(args) < 2 {
				break
			}
			attr := slog.Any(x, args[1])
			tags[attr.Key] = attr.Value.String()
			args = args[2:]
		default:
			args = args[1:]
		}
	}
	// add tags from logger:
	for k, v := range nl.tags {
		tags[k] = v
	}
	return tags
}

func (nl *CoreLogger) SetTags(tags Tags) {
	for tag := range tags {
		nl.tags[tag] = tags[tag]
	}
}

// CaptureError logs an error and sends it to sentry.
func (nl *CoreLogger) CaptureError(msg string, err error, args ...interface{}) {
	nl.Logger.Error(msg, args...)
	if err != nil {
		// convert args to tags to pass to sentry:
		tags := nl.tagsFromArgs(args...)
		// send error to sentry:
		CaptureException(err, tags)
	}
}

// Fatal logs an error at the fatal level.
func (nl *CoreLogger) Fatal(msg string, err error, args ...interface{}) {
	args = append(args, "error", err)
	nl.Logger.Log(context.TODO(), LevelFatal, msg, args...)
}

// FatalAndPanic logs an error at the fatal level and panics.
func (nl *CoreLogger) FatalAndPanic(msg string, err error, args ...interface{}) {
	nl.Fatal(msg, err, args...)
	if err != nil {
		panic(err)
	}
}

// CaptureFatal logs an error at the fatal level and sends it to sentry.
func (nl *CoreLogger) CaptureFatal(msg string, err error, args ...interface{}) {
	// todo: make sure this level is printed nicely
	nl.Logger.Log(context.TODO(), LevelFatal, msg, args...)

	if err != nil {
		// convert args to tags to pass to sentry:
		tags := nl.tagsFromArgs(args...)
		// send error to sentry:
		CaptureException(err, tags)
	}
}

// CaptureFatalAndPanic logs an error at the fatal level and sends it to sentry.
// It then panics.
func (nl *CoreLogger) CaptureFatalAndPanic(msg string, err error, args ...interface{}) {
	nl.CaptureFatal(msg, err, args...)
	if err != nil {
		panic(err)
	}
}

// CaptureWarn logs a warning and sends it to sentry.
func (nl *CoreLogger) CaptureWarn(msg string, args ...interface{}) {
	nl.Logger.Warn(msg, args...)

	tags := nl.tagsFromArgs(args...)
	// send message to sentry:
	CaptureMessage(msg, tags)
}

// CaptureInfo logs an info message and sends it to sentry.
func (nl *CoreLogger) CaptureInfo(msg string, args ...interface{}) {
	nl.Logger.Info(msg, args...)

	tags := nl.tagsFromArgs(args...)
	// send message to sentry:
	CaptureMessage(msg, tags)
}

// Reraise is used to capture unexpected panics with sentry and reraise them.
func (nl *CoreLogger) Reraise(args ...any) {
	if err := recover(); err != nil {
		Reraise(err, nl.tagsFromArgs(args...))
	}
}

func NewNoOpLogger() *CoreLogger {
	return NewCoreLogger(slog.New(slog.NewJSONHandler(io.Discard, nil)), nil)
}
