package main

import (
	"context"
	"flag"
	"log/slog"
	_ "net/http/pprof"
	"os"
	"runtime"
	"runtime/trace"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
)

// this is set by the build script and used by the observability package
var commit string

func init() {
	runtime.SetBlockProfileRate(1)
}

func main() {
	portFilename := flag.String(
		"port-filename",
		"port_file.txt",
		"filename for port to communicate with client",
	)
	pid := flag.Int("pid", 0, "pid")
	debug := flag.Bool("debug", false, "debug mode")
	noAnalytics := flag.Bool("no-observability", false, "turn off observability")
	// todo: remove these flags, they are here for backward compatibility
	serveSock := flag.Bool("serve-sock", false, "use sockets")

	flag.Parse()

	ctx := context.Background()
	// set up sentry reporting
	observability.InitSentry(*noAnalytics, commit)
	defer sentry.Flush(2)

	// store commit hash in context
	ctx = context.WithValue(ctx, observability.Commit("commit"), commit)

	var loggerPath string
	file, _ := observability.GetLoggerPath()
	if file != nil {
		level := slog.LevelInfo
		// TODO: replace this with the debug flag
		if os.Getenv("WANDB_CORE_DEBUG") != "" {
			level = slog.LevelDebug
		}
		opts := &slog.HandlerOptions{
			Level:     level,
			AddSource: true,
		}
		logger := slog.New(slog.NewJSONHandler(file, opts))
		slog.SetDefault(logger)
		slog.Info("started logging")
		logger.LogAttrs(
			ctx,
			slog.LevelDebug,
			"Flags",
			slog.String("fname", *portFilename),
			slog.Int("pid", *pid),
			slog.Bool("debug", *debug),
			slog.Bool("noAnalytics", *noAnalytics),
			slog.Bool("serveSock", *serveSock),
		)
		loggerPath = file.Name()
		defer file.Close()
	}

	if os.Getenv("_WANDB_TRACE") != "" {
		f, err := os.Create("trace.out")
		if err != nil {
			slog.Error("failed to create trace output file", "err", err)
			panic(err)
		}
		defer func() {
			if err = f.Close(); err != nil {
				slog.Error("failed to close trace file", "err", err)
				panic(err)
			}
		}()

		if err = trace.Start(f); err != nil {
			slog.Error("failed to start trace", "err", err)
			panic(err)
		}
		defer trace.Stop()
	}
	serve := server.NewServer(ctx, "127.0.0.1:0", *portFilename)
	serve.SetDefaultLoggerPath(loggerPath)
	serve.Close()
}
