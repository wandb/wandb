package server

import (
	"fmt"
	"io"
	"log/slog"
	"sync/atomic"
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

var earlyLogger atomic.Value

type EarlyLogger struct {
	active bool
	bufWriter io.Writer
	bytesBuffer bytes.Buffer
}

func NewEarlyLogger() *EarlyLogger {
	return &EarlyLogger{}
}

func SetupEarlyLogger() {
	earlyLogger.Store(NewEarlyLogger())
}

func transitionFromEarlyLogger() {
	// can only transition once
	if !earlyLogging {
		return
	}

	// switch default logger to transition logger

	// open up new log destination

	// what do we do with transition logger, it might keep getting new data
	// maybe we try a few times then we give up and log that it keeps getting filled and
	// that we dropped some data
}

func SetupDefaultLogger() *slog.Logger {
	var writers []io.Writer

	SetupEarlyLogger()
	// todo: discover system temp lib
	name := "/tmp/logs.txt"
	var buf bytes.Buffer
	bufWriter := bufio.NewWriter(&buf)

	slogger := slog.New(slog.NewTextHandler(bufWriter, nil))
	file, err := os.OpenFile(name, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		fmt.Println("FATAL Problem", err)
	} else {
		writers = append(writers, file)
	}
	if os.Getenv("WANDB_NEXUS_DEBUG") != "" {
		writers = append(writers, os.Stderr)
	}

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
