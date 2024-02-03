package main

import (
	"context"
	"flag"
	"io"
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

	var writers []io.Writer

	var loggerPath string
	file, err := observability.GetLoggerPath()
	if err == nil {
		writers = append(writers, file)
		loggerPath = file.Name()
	}
	if file != nil {
		defer file.Close()
	}

	if os.Getenv("WANDB_CORE_DEBUG") != "" {
		writers = append(writers, os.Stderr)
	}
	logger := server.SetupDefaultLogger(writers...)
	ctx := context.Background()

	// set up sentry reporting
	observability.InitSentry(*noAnalytics, commit)
	defer sentry.Flush(2)

	// store commit hash in context
	ctx = context.WithValue(ctx, observability.Commit("commit"), commit)

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
