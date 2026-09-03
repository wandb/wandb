package stream

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
)

// streamLoggerFile is a file that backs a Stream's logger.
type streamLoggerFile *os.File

// streamLoggerProviders provides stream logging-related bindings.
var streamLoggerProviders = wire.NewSet(
	openStreamLoggerFile,
	streamLogger,
	streamOTelProxy,
)

// streamOTelProxy returns the OpenTelemetry proxy for the stream.
//
// The stream owns the proxy's lifecycle: it is shut down in Stream.Close
// after all of the stream's work is processed.
func streamOTelProxy(s *settings.Settings) *analytics.OpenTelemetryProxy {
	return analytics.NewOpenTelemetryProxy(context.Background(), s, "wandb-core")
}

// symlinkDebugCore symlinks the debug-core.log file to the run's directory.
func symlinkDebugCore(
	s *settings.Settings,
	loggerPath string,
) {
	if loggerPath == "" {
		return
	}

	targetPath := filepath.Join(s.GetLogDir(), "debug-core.log")

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
	telemetryProxy *analytics.OpenTelemetryProxy,
	s *settings.Settings,
	logLevel slog.Level,
) *observability.CoreLogger {
	var writer io.Writer
	if loggerFile != nil {
		writer = (*os.File)(loggerFile)
	} else {
		writer = io.Discard
	}

	telemetryTags := observability.Tags{
		"run_id":   s.GetRunID(),
		"run_url":  s.GetRunURL(),
		"project":  s.GetProject(),
		"base_url": s.GetBaseURL(),
	}
	if s.GetSweepURL() != "" {
		telemetryTags["sweep_url"] = s.GetSweepURL()
	}

	telemetryRecorder := analytics.NewTelemetryRecorder(
		telemetryProxy,
		analytics.NewTelemetryContext(),
	)

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{
				Level: logLevel,
				// AddSource: true,
			},
		)),
		telemetryRecorder,
	).With(nil, telemetryTags)

	logger.CaptureInfo("wandb-core")
	logger.Info("stream: starting", "core version", version.Version)
	return logger
}

// openStreamLoggerFile opens the stream's log file (debug-internal.log).
//
// On failure, this will log to the global log file (debug-core.log)
// and return nil.
func openStreamLoggerFile(s *settings.Settings) streamLoggerFile {
	path := s.GetInternalLogFile()
	loggerFile, err := os.OpenFile(
		path,
		os.O_APPEND|os.O_CREATE|os.O_WRONLY,
		0o666,
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
