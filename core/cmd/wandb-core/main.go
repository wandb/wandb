package main

import (
	"flag"
	"fmt"
	"log/slog"
	_ "net/http/pprof"
	"os"
	"runtime"
	"runtime/trace"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/processlib"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/server"
)

// this is set by the build script and used by the observability package
var commit string

func main() {
	// Flags to control the server
	portFilename := flag.String("port-filename", "port_file.txt",
		"Specifies the filename where the server will write the port number it uses to "+
			"communicate with clients.")
	pid := flag.Int("pid", 0,
		"Specifies the process ID (PID) of the external process that spins up this service.")
	logLevel := flag.Int("log-level", 0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.")
	disableAnalytics := flag.Bool("no-observability", false,
		"Disables observability features such as metrics and logging analytics.")
	enableOsPidShutdown := flag.Bool("os-pid-shutdown", false,
		"Enables automatic server shutdown when the external process identified by the PID terminates.")
	traceFile := flag.String("trace-file", "",
		"Specifies the file to write the trace to, if empty, profiling is disabled.")

	// Custom usage function to add a header, version, and commit info
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "============================================\n")
		fmt.Fprintf(os.Stderr, "      WANDB Core Service Configuration      \n")
		fmt.Fprintf(os.Stderr, "============================================\n")
		fmt.Fprintf(os.Stderr, "Version: %s\n", version.Version)
		fmt.Fprintf(os.Stderr, "Commit SHA: %s\n\n", commit)
		fmt.Fprintf(os.Stderr, "Use the following flags to configure the wandb sdk service:\n\n")
		flag.PrintDefaults() // Print the default help for all flags
	}

	flag.Parse()

	var shutdownOnParentExitEnabled bool
	if *pid != 0 && *enableOsPidShutdown {
		// Shutdown this process if the parent pid exits (if supported by the OS)
		shutdownOnParentExitEnabled = processlib.ShutdownOnParentExit(*pid)
	}

	// set up sentry reporting
	sentryClient := sentry_ext.New(sentry_ext.Params{
		Disabled:         *disableAnalytics,
		AttachStacktrace: true,
		Release:          version.Version,
		Commit:           commit,
		Environment:      version.Environment,
	})
	defer sentryClient.Flush(2)

	var loggerPath string
	if file, err := observability.GetLoggerPath(); err != nil {
		slog.Error("failed to get logger path", "error", err)
	} else {
		logger := slog.New(
			slog.NewJSONHandler(
				file,
				&slog.HandlerOptions{
					Level:     slog.Level(*logLevel),
					AddSource: false,
				},
			),
		)
		slog.SetDefault(logger)
		slog.Info(
			"main: starting server",
			"port-filename", *portFilename,
			"pid", *pid,
			"log-level", *logLevel,
			"disable-analytics", *disableAnalytics,
			"shutdown-on-parent-exit", shutdownOnParentExitEnabled,
		)
		loggerPath = file.Name()
		defer file.Close()
	}

	if *traceFile != "" {
		runtime.SetBlockProfileRate(1)
		f, err := os.Create(*traceFile)
		if err != nil {
			slog.Error("failed to create trace output file", "err", err)
			panic(err)
		}
		defer func() {
			if err = f.Close(); err != nil {
				slog.Error("failed to close trace file", "err", err)
			}
		}()

		if err = trace.Start(f); err != nil {
			slog.Error("failed to start trace", "err", err)
			panic(err)
		}
		defer trace.Stop()
	}

	srv, err := server.NewServer(
		&server.ServerParams{
			ListenIPAddress: "127.0.0.1:0",
			PortFilename:    *portFilename,
			ParentPid:       *pid,
			SentryClient:    sentryClient,
			Commit:          commit,
			LoggerPath:      loggerPath,
			LogLevel:        slog.Level(*logLevel),
		},
	)
	if err != nil {
		slog.Error("failed to start server, exiting", "error", err)
		return
	}
	srv.Serve()
}
