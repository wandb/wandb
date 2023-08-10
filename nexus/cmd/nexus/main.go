package main

import (
	"context"
	"flag"
	_ "net/http/pprof"
	"os"
	"runtime"
	"runtime/trace"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/server"
	"golang.org/x/exp/slog"
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
	// todo: remove these flags, they are here for backwards compatibility
	serveSock := flag.Bool("serve-sock", false, "use sockets")
	serveGrpc := flag.Bool("serve-grpc", false, "use grpc")

	flag.Parse()

	logger := server.SetupDefaultLogger()
	ctx := context.Background()

	// set up sentry reporting
	observability.InitSentry(*noAnalytics, commit)
	defer sentry.Flush(2)

	logger.LogAttrs(
		ctx,
		slog.LevelDebug,
		"Flags",
		slog.String("fname", *portFilename),
		slog.Int("pid", *pid),
		slog.Bool("debug", *debug),
		slog.Bool("noAnalytics", *noAnalytics),
		slog.Bool("serveSock", *serveSock),
		slog.Bool("serveGrpc", *serveGrpc),
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

	nexus := server.NewServer(ctx, "127.0.0.1:0", *portFilename)
	nexus.Close()
}
