package stream

import (
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
)

// streamLoggerFile is a file that backs a Stream's logger.
type streamLoggerFile *os.File

// streamLoggerProviders provides stream logging-related bindings.
var streamLoggerProviders = wire.NewSet(
	openStreamLoggerFile,
	streamLogger,
)

// symlinkDebugCore symlinks the debug-core.log file to the run's directory.
func symlinkDebugCore(
	settings *settings.Settings,
	loggerPath string,
) {
	if loggerPath == "" {
		return
	}

	targetPath := filepath.Join(settings.GetLogDir(), "debug-core.log")

	err := os.Symlink(loggerPath, targetPath)
	if err != nil {
		slog.Error(
			"error symlinking debug-core.log",
			"loggerPath", loggerPath,
			"targetPath", targetPath,
			"error", err)
	}
}

// streamLogger initializes a logger for the run.
func streamLogger(
	loggerFile streamLoggerFile,
	settings *settings.Settings,
	sentryClient *sentry_ext.Client,
	logLevel slog.Level,
) *observability.CoreLogger {
	sentryClient.SetUser(
		settings.GetEntity(),
		settings.GetEmail(),
		settings.GetUserName(),
	)

	var writer io.Writer
	if loggerFile != nil {
		writer = (*os.File)(loggerFile)
	} else {
		writer = io.Discard
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{
				Level: logLevel,
				// AddSource: true,
			},
		)),
		&observability.CoreLoggerParams{
			Tags:   observability.Tags{},
			Sentry: sentryClient,
		},
	)

	logger.Info(
		"stream: starting",
		"core version", version.Version)

	tags := observability.Tags{
		"run_id":   settings.GetRunID(),
		"run_url":  settings.GetRunURL(),
		"project":  settings.GetProject(),
		"base_url": settings.GetBaseURL(),
	}
	if settings.GetSweepURL() != "" {
		tags["sweep_url"] = settings.GetSweepURL()
	}
	logger.SetGlobalTags(tags)

	return logger
}

// openStreamLoggerFile opens the stream's log file (debug-internal.log).
//
// On failure, this will log to the global log file (debug-core.log)
// and return nil.
func openStreamLoggerFile(settings *settings.Settings) streamLoggerFile {
	path := settings.GetInternalLogFile()
	loggerFile, err := os.OpenFile(
		path,
		os.O_APPEND|os.O_CREATE|os.O_WRONLY,
		0666,
	)

	if err != nil {
		slog.Error(
			"error opening log file",
			"path", path,
			"error", err)
		return nil
	} else {
		return loggerFile
	}
}
