package stream

import (
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/getsentry/sentry-go"
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
	streamSentryContext,
	streamTelemetryProxy,
	streamLogger,
)

// streamTelemetryProxy creates the OpenTelemetry proxy for the stream.
//
// Telemetry is sent to the W&B backend's OpenTelemetry proxy API at the run's
// base URL. The endpoint is only known once the client's settings arrive, so
// the proxy is constructed per-stream here rather than at server startup.
//
// Offline runs get a no-op proxy since there is no backend to send to.
func streamTelemetryProxy(s *settings.Settings) analytics.OpenTelemetryProxy {
	if s.IsOffline() {
		return analytics.NoopOpenTelemetryProxy{}
	}

	return analytics.NewOpenTelemetryProxy(
		s.GetBaseURL(),
		s.GetAPIKey(),
	)
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

// streamSentryContext returns the Sentry context for the stream.
//
// Returns nil if the run is offline.
func streamSentryContext(s *settings.Settings) *observability.SentryContext {
	if s.IsOffline() {
		return nil
	}

	sentryCtx := observability.NewSentryContext(sentry.CurrentHub())
	sentryCtx.SetUser(sentry.User{
		ID:    s.GetEntity(),
		Email: s.GetEmail(),
		Name:  s.GetUserName(),
	})
	return sentryCtx
}

// streamLogger initializes a logger for the run.
func streamLogger(
	loggerFile streamLoggerFile,
	sentryCtx *observability.SentryContext,
	telemetryProxy analytics.OpenTelemetryProxy,
	s *settings.Settings,
	logLevel slog.Level,
) *observability.CoreLogger {
	var writer io.Writer
	if loggerFile != nil {
		writer = (*os.File)(loggerFile)
	} else {
		writer = io.Discard
	}

	sentryOnlyTags := observability.Tags{
		"run_id":   s.GetRunID(),
		"run_url":  s.GetRunURL(),
		"project":  s.GetProject(),
		"base_url": s.GetBaseURL(),
	}
	if s.GetSweepURL() != "" {
		sentryOnlyTags["sweep_url"] = s.GetSweepURL()
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{
				Level: logLevel,
				// AddSource: true,
			},
		)),
		sentryCtx,
		telemetryProxy,
	).With(nil, sentryOnlyTags)

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
