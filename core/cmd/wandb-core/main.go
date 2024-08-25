package main

import (
	"context"
	"flag"
	"log/slog"

	"github.com/wandb/wandb/core/internal/processlib"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
)

const (
	SentryDSN = "https://0d0c6674e003452db392f158c42117fb@o151352.ingest.sentry.io/4505513612214272"
	// Use for testing:
	// SentryDSN = "https://45bbbb93aacd42cf90785517b66e925b@o151352.ingest.us.sentry.io/6438430"
)

// this is set by the build script and used by the observability package
var commit string

func main() {
	// Flags to control the server
	portFilename := flag.String("port-filename", "port_file.txt", "filename for port to communicate with client")
	pid := flag.Int("pid", 0, "pid of the process to communicate with")
	enableDebugLogging := flag.Bool("debug", false, "enable debug logging")
	disableAnalytics := flag.Bool("no-observability", false, "turn off observability")
	enableOsPidShutdown := flag.Bool("os-pid-shutdown", false, "enable OS pid shutdown")
	_ = flag.String("trace", "", "file name to write trace output to")
	// TODO: remove these flags, they are here for backward compatibility
	_ = flag.Bool("serve-sock", false, "use sockets")

	flag.Parse()

	var shutdownOnParentExitEnabled bool
	if *pid != 0 && *enableOsPidShutdown {
		// Shutdown this process if the parent pid exits (if supported by the OS)
		shutdownOnParentExitEnabled = processlib.ShutdownOnParentExit(*pid)
	}

	// set up sentry reporting
	params := sentry_ext.Params{
		DSN:              SentryDSN,
		AttachStacktrace: true,
		Release:          version.Version,
		Commit:           commit,
		Environment:      version.Environment,
	}
	if *disableAnalytics {
		params.DSN = ""
	}
	sentryClient := sentry_ext.New(params)
	defer sentryClient.Flush(2)

	// store commit hash in context
	ctx := context.Background()
	ctx = context.WithValue(ctx, observability.Commit, commit)

	var loggerPath string
	if file, _ := observability.GetLoggerPath(); file != nil {
		level := slog.LevelInfo
		if *enableDebugLogging {
			level = slog.LevelDebug
		}
		opts := &slog.HandlerOptions{
			Level:     level,
			AddSource: false,
		}
		logger := slog.New(slog.NewJSONHandler(file, opts))
		slog.SetDefault(logger)
		logger.LogAttrs(
			ctx,
			slog.LevelInfo,
			"started logging, with flags",
			slog.String("port-filename", *portFilename),
			slog.Int("pid", *pid),
			slog.Bool("debug", *enableDebugLogging),
			slog.Bool("disable-analytics", *disableAnalytics),
		)
		slog.Info("FeatureState", "shutdownOnParentExitEnabled", shutdownOnParentExitEnabled)
		loggerPath = file.Name()
		defer file.Close()
	}

	// if *traceFile != "" {
	// 	f, err := os.Create(*traceFile)
	// 	if err != nil {
	// 		slog.Error("failed to create trace output file", "err", err)
	// 		panic(err)
	// 	}
	// 	defer func() {
	// 		if err = f.Close(); err != nil {
	// 			slog.Error("failed to close trace file", "err", err)
	// 		}
	// 	}()

	// 	if err = trace.Start(f); err != nil {
	// 		slog.Error("failed to start trace", "err", err)
	// 		panic(err)
	// 	}
	// 	defer trace.Stop()
	// }

	srv, err := server.NewServer(
		ctx,
		&server.ServerParams{
			ListenIPAddress: "127.0.0.1:0",
			PortFilename:    *portFilename,
			ParentPid:       *pid,
			SentryClient:    sentryClient,
			Commit:          commit,
		},
	)
	if err != nil {
		slog.Error("failed to start server, exiting", "error", err)
		return
	}
	srv.SetDefaultLoggerPath(loggerPath)
	srv.Serve()
}
