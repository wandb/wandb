package main

import (
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

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
	enableDCGMProfiling := flag.Bool("enable-dcgm-profiling", false,
		"Enables collection of profiling metrics for Nvidia GPUs using DCGM. Requires a running `nvidia-dcgm` service.")

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
			"enable-dcgm-profiling", *enableDCGMProfiling,
		)
		loggerPath = file.Name()
		defer func() {
			_ = file.Close()
		}()
	}

	// Log when we receive a shutdown signal
	c := make(chan os.Signal, 1)
	signal.Notify(c, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		sig := <-c
		slog.Info("received shutdown signal", "signal", sig)
		os.Exit(0)
	}()

	srv, err := server.NewServer(
		&server.ServerParams{
			ListenIPAddress:     "127.0.0.1:0",
			PortFilename:        *portFilename,
			ParentPid:           *pid,
			SentryClient:        sentryClient,
			Commit:              commit,
			LoggerPath:          loggerPath,
			LogLevel:            slog.Level(*logLevel),
			EnableDCGMProfiling: *enableDCGMProfiling,
		},
	)
	if err != nil {
		slog.Error("failed to start server, exiting", "error", err)
		return
	}
	srv.Serve()
}
