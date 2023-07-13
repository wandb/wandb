package main

import (
	"context"
	"flag"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/nexus/pkg/analytics"
	"github.com/wandb/wandb/nexus/pkg/server"
	"golang.org/x/exp/slog"
)

// this is set by the build script and used by the analytics package
var commit string

func main() {
	portFilename := flag.String(
		"port-filename",
		"port_file.txt",
		"filename for port to communicate with client",
	)
	pid := flag.Int("pid", 0, "pid")
	debug := flag.Bool("debug", false, "debug mode")
	noAnalytics := flag.Bool("no-analytics", false, "turn off analytics")
	// todo: remove these flags, they are here for backwards compatibility
	serveSock := flag.Bool("serve-sock", false, "use sockets")
	serveGrpc := flag.Bool("serve-grpc", false, "use grpc")

	flag.Parse()

	logger := server.SetupDefaultLogger()
	ctx := context.Background()

	// set up sentry reporting
	analytics.InitSentry(*noAnalytics, commit)
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

	nexus := server.NewServer(ctx, "127.0.0.1:0", *portFilename)
	nexus.Close()
}
