package server

import (
	"context"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

func SetupLogger(toStderr bool) {
	file, err := os.OpenFile("/tmp/logs.txt", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		fmt.Println("FATAL Problem", err)
		panic("problem")
	}
	var writer io.Writer
	if toStderr {
		writer = io.MultiWriter(os.Stderr, file)
	} else {
		writer = file
	}

	opts := &slog.HandlerOptions{
		Level: slog.LevelDebug,
	}
	logger := slog.New(slog.NewJSONHandler(writer, opts))
	slog.SetDefault(logger)
	slog.Info("started logging")
}

func LogError(msg string, err error) {
	slog.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("error", err.Error()))
}

func LogFatal(msg string) {
	slog.LogAttrs(context.Background(),
		slog.LevelError,
		msg)
	panic(msg)
}

func LogFatalError(msg string, err error) {
	slog.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("error", err.Error()))
	panic(msg)
}

func LogRecord(msg string, record *service.Record) {
	slog.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("record", record.String()))
}

func LogResult(msg string, result *service.Result) {
	slog.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("result", result.String()))
}
