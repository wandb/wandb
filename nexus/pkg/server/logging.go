package server

import (
	"fmt"
	"io"
	"log/slog"
	"os"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

func setupLogger(opts *slog.HandlerOptions, writers ...io.Writer) *slog.Logger {
	level := slog.LevelInfo
	if os.Getenv("WANDB_NEXUS_DEBUG") != "" {
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

func SetupStreamLogger(name string, settings *service.Settings) *observability.NexusLogger {
	var writers []io.Writer

	file, err := os.OpenFile(name, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		fmt.Println("FATAL Problem", err)
	} else {
		writers = append(writers, file)
	}
	if os.Getenv("WANDB_NEXUS_DEBUG") != "" {
		writers = append(writers, os.Stderr)
	}

	writer := io.MultiWriter(writers...)
	tags := make(observability.Tags)
	tags["run_id"] = settings.GetRunId().GetValue()
	tags["run_url"] = settings.GetRunUrl().GetValue()
	tags["project"] = settings.GetProject().GetValue()
	tags["entity"] = settings.GetEntity().GetValue()

	return observability.NewNexusLogger(setupLogger(nil, writer), tags)
}
