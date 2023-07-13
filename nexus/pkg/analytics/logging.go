package analytics

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

const LevelFatal = slog.Level(12)

type NexusLogger struct {
	*slog.Logger
	tags map[string]string
}

func NewNexusLogger(logger *slog.Logger, settings *service.Settings) *NexusLogger {
	tags := make(map[string]string)
	tags["run_id"] = settings.GetRunId().GetValue()
	tags["run_url"] = settings.GetRunUrl().GetValue()
	tags["project"] = settings.GetProject().GetValue()
	tags["entity"] = settings.GetEntity().GetValue()

	for tag := range tags {
		logger = logger.With(slog.String(tag, tags[tag]))
	}

	return &NexusLogger{Logger: logger, tags: tags}
}

func (nl *NexusLogger) tagsFromArgs(args ...any) map[string]string {
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

func (nl *NexusLogger) Error(msg string, err error, args ...interface{}) {
	nl.Logger.Error(msg, args...)
	if err != nil {
		// convert args to tags to pass to sentry:
		tags := nl.tagsFromArgs(args...)
		// send error to sentry:
		CaptureException(err, tags)
	}
}

// Fatal is like Error but panics after logging.
func (nl *NexusLogger) Fatal(msg string, err error, args ...interface{}) {
	// todo: make sure this level is printed nicely
	nl.Logger.Log(context.TODO(), LevelFatal, msg, args...)

	if err != nil {
		// convert args to tags to pass to sentry:
		tags := nl.tagsFromArgs(args...)
		// send error to sentry:
		CaptureException(err, tags)
	}

	panic(err)
}

func (nl *NexusLogger) Warn(msg string, args ...interface{}) {
	nl.Logger.Warn(msg, args...)

	tags := nl.tagsFromArgs(args...)
	// send message to sentry:
	CaptureMessage(msg, tags)
}
