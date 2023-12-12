package server

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

func setupLogger(opts *slog.HandlerOptions, writers ...io.Writer) *slog.Logger {
	level := slog.LevelInfo
	if os.Getenv("WANDB_CORE_DEBUG") != "" {
		level = slog.LevelDebug
	}

	writer := io.MultiWriter(writers...)
	if opts == nil {
		opts = &slog.HandlerOptions{
			Level: level,
		}
	}
	logger := slog.New(slog.NewJSONHandler(writer, opts))
	return logger
}

func SetupDefaultLogger(writers ...io.Writer) *slog.Logger {

	logger := setupLogger(nil, writers...)
	slog.SetDefault(logger)
	slog.Info("started logging")
	return logger
}

// TODO: add a noop logger

func SetupStreamLogger(settings *service.Settings) *observability.CoreLogger {
	// TODO: when we add session concept re-do this to use user provided path
	targetPath := filepath.Join(settings.GetLogDir().GetValue(), "core-debug.log")
	if path := defaultLoggerPath.Load(); path != nil {
		path := path.(string)
		// check path exists
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			err := os.Symlink(path, targetPath)
			if err != nil {
				slog.Error("error creating symlink", "error", err)
			}
		}
	}

	var writers []io.Writer
	name := settings.GetLogInternal().GetValue()

	file, err := os.OpenFile(name, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		slog.Error(fmt.Sprintf("error opening log file: %s", err))
	} else {
		writers = append(writers, file)
	}
	if os.Getenv("WANDB_CORE_DEBUG") != "" {
		writers = append(writers, os.Stderr)
	}

	writer := io.MultiWriter(writers...)

	logger := observability.NewCoreLogger(
		setupLogger(nil, writer),
		observability.WithTags(observability.Tags{}),
		observability.WithCaptureMessage(observability.CaptureMessage),
		observability.WithCaptureException(observability.CaptureException),
	)
	logger.Info("using version", "core version", version.Version)
	logger.Info("created symlink", "path", targetPath)
	tags := observability.Tags{
		"run_id":  settings.GetRunId().GetValue(),
		"run_url": settings.GetRunUrl().GetValue(),
		"project": settings.GetProject().GetValue(),
		"entity":  settings.GetEntity().GetValue(),
	}
	logger.SetTags(tags)

	return logger
}
