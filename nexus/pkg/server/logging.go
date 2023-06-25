package server

import (
	"context"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

func setupLogger(fname string) *slog.Logger {
	toStderr := os.Getenv("WANDB_NEXUS_DEBUG") != ""
	file, err := os.OpenFile(fname, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
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
	return logger
}

func SetupDefaultLogger() {
	logger := setupLogger("/tmp/logs.txt")
	slog.SetDefault(logger)
	slog.Info("started logging")
}

func SetupStreamLogger(logFile string, streamID string) *slog.Logger {
	logger := setupLogger(logFile)
	return logger
	/*
		toStderr := os.Getenv("WANDB_NEXUS_DEBUG") != ""
		opts := &slog.HandlerOptions{
			Level: slog.LevelDebug,
		}
		logger := slog.New(slog.NewJSONHandler(writer, opts))
		jsonHandler := slog.NewTextHandler(os.Stdout).
			WithAttrs([]slog.Attr{slog.String("app-version", "v0.0.1-beta")})
		logger := slog.New(textHandler)
		return logger
	*/
}

func LogError(log *slog.Logger, msg string, err error) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("error", err.Error()))
}

func LogFatal(log *slog.Logger, msg string) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg)
	panic(msg)
}

func LogFatalError(log *slog.Logger, msg string, err error) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("error", err.Error()))
	panic(msg)
}

func LogRecord(log *slog.Logger, msg string, record *service.Record) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("record", record.String()))
}

func LogResult(log *slog.Logger, msg string, result *service.Result) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("result", result.String()))
}
