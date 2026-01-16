// Command wandb-core provides the W&B SDK core service and the "leet" terminal UI
// in a single binary. The default mode runs the core service; the `leet` subcommand
// launches the local TUI for inspecting a run.
//
// Usage:
//
//	wandb-core [service flags]
//	wandb-core leet [<wandb-directory>] [leet flags]
//
// Service flags: see `wandb-core -h`.
// Leet flags:    see `wandb-core leet -h`.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"net/http/pprof"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/processlib"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/server"
)

// commit hash is set by the build script.
var commit string

const (
	exitCodeSuccess       = 0 // normal exit
	exitCodeErrorInternal = 1 // some error occurred
	exitCodeErrorArgs     = 2 // incorrect command-line flags
)

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	if len(args) > 0 && args[0] == "leet" {
		return leetMain(args[1:])
	}
	return serviceMain()
}

// serviceMain runs the default W&B SDK core service.
func serviceMain() int {
	portFilename := flag.String("port-filename", "port_file.txt",
		"Specifies the filename where the server will write the port number it uses to "+
			"communicate with clients.")
	pid := flag.Int("pid", 0,
		"Specifies the process ID (PID) of the external process that spins up this service.")
	logLevel := flag.Int("log-level", 0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.")
	disableAnalytics := flag.Bool("no-observability", false,
		"Disables observability features such as metrics and logging analytics.")
	enableOsPidShutdown := flag.Bool(
		"os-pid-shutdown",
		false,
		"Enables automatic server shutdown when the external process identified by the PID terminates.",
	)
	enableDCGMProfiling := flag.Bool(
		"enable-dcgm-profiling",
		false,
		"Enables collection of profiling metrics for Nvidia GPUs using DCGM. Requires a running `nvidia-dcgm` service.",
	)
	listenOnLocalhost := flag.Bool("listen-on-localhost", false,
		"Whether to listen on a localhost socket. This is less secure than"+
			" Unix sockets, but some clients do not support them"+
			" (in particular, Python on Windows).")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "wandb-core - W&B SDK core service\n\n")
		fmt.Fprintf(os.Stderr, "Version: %s\n", version.Version)
		fmt.Fprintf(os.Stderr, "Commit SHA: %s\n\n", commit)
		fmt.Fprintf(os.Stderr, "Usage:\n")
		fmt.Fprintf(os.Stderr, "  wandb-core [flags]\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		fmt.Fprintf(os.Stderr, "  -h, --help            Show this help message\n\n")
		fmt.Fprintf(os.Stderr, "Flags:\n")
		flag.PrintDefaults()
	}

	flag.Parse()

	var shutdownOnParentExitEnabled bool
	if *pid != 0 && *enableOsPidShutdown {
		shutdownOnParentExitEnabled = processlib.ShutdownOnParentExit(*pid)
	}

	// Sentry (disabled if --no-observability)
	sentryClient := sentry_ext.New(sentry_ext.Params{
		Disabled:         *disableAnalytics,
		AttachStacktrace: true,
		Release:          version.Version,
		Commit:           commit,
		Environment:      version.Environment,
	})
	defer sentryClient.Flush(2)

	// Structured logging to file selected by observability package.
	var loggerPath string
	if file, err := observability.GetLoggerPath(); err != nil {
		slog.Error("main: failed to get logger path", "error", err)
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
		defer func() { _ = file.Close() }()
	}

	// Graceful shutdown on SIGINT/SIGTERM.
	c := make(chan os.Signal, 1)
	signal.Notify(c, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		sig := <-c
		slog.Info("main: received shutdown signal", "signal", sig)
		os.Exit(0)
	}()

	srv := server.NewServer(
		server.ServerParams{
			Commit:              commit,
			EnableDCGMProfiling: *enableDCGMProfiling,
			ListenOnLocalhost:   *listenOnLocalhost,
			LoggerPath:          loggerPath,
			LogLevel:            slog.Level(*logLevel),
			ParentPID:           *pid,
			SentryClient:        sentryClient,
		},
	)

	if err := srv.Serve(*portFilename); err != nil {
		slog.Error("main: Serve() returned error", "error", err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

// leetMain runs the TUI subcommand.
func leetMain(args []string) int {
	fs := flag.NewFlagSet("leet", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	logLevel := fs.Int("log-level", 0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.")
	disableAnalytics := fs.Bool("no-observability", false,
		"Disables observability features such as metrics and logging analytics.")
	runFile := fs.String("run-file", "",
		"Path to a .wandb file to open directly in single-run view.")

	pprofAddr := fs.String("pprof", "",
		"If set, serves /debug/pprof/* on this address (e.g. 127.0.0.1:6060).")
	pprofBlockRate := fs.Int("pprof-block-rate", 0,
		"If >0, sets runtime.SetBlockProfileRate(n).")
	pprofMutexFraction := fs.Int("pprof-mutex-fraction", 0,
		"If >0, sets runtime.SetMutexProfileFraction(n).")

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, `wandb-core leet - Lightweight Experiment Exploration Tool
A terminal UI for viewing your W&B runs locally.

Usage:
  wandb-core leet [flags] <wandb-directory>

Arguments:
  <wandb-directory>  Path to the wandb directory containing run folders.

Options:
  -h, --help         Show this help message

Flags:
`)
		fs.PrintDefaults()
	}

	if err := fs.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return exitCodeSuccess
		}
		return exitCodeErrorArgs
	}

	pprofStop, pprofURL, err := startPprofServer(*pprofAddr, *pprofBlockRate, *pprofMutexFraction)
	if err != nil {
		fmt.Fprintln(os.Stderr, "pprof:", err)
		return exitCodeErrorArgs
	}
	if pprofStop != nil {
		// Print to stderr so you see it even if normal logging is discarded.
		fmt.Fprintln(os.Stderr, "pprof:", pprofURL)
		defer func() {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			_ = pprofStop(ctx)
		}()
	}

	// Configure Sentry reporting.
	sentryClient := sentry_ext.New(sentry_ext.Params{
		DSN:              sentry_ext.LeetSentryDSN,
		Disabled:         *disableAnalytics,
		AttachStacktrace: true,
		Release:          version.Version,
		Environment:      version.Environment,
	})
	sentryClient.CaptureMessage("wandb-leet", nil)
	defer sentryClient.Flush(2)

	// Configure debug logging.
	logWriter := io.Discard
	// TODO: Create a log file not only if debug logging is requested.
	if *logLevel == -4 {
		loggerFile, err := os.OpenFile(
			"wandb-leet.debug.log",
			os.O_WRONLY|os.O_CREATE|os.O_TRUNC,
			0644,
		)
		if err != nil {
			fmt.Println("fatal:", err)
			return exitCodeErrorInternal
		}
		logWriter = loggerFile
		defer func() { _ = loggerFile.Close() }()
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			logWriter,
			&slog.HandlerOptions{Level: slog.Level(*logLevel)},
		)),
		&observability.CoreLoggerParams{
			Tags:   observability.Tags{},
			Sentry: sentryClient,
		},
	)

	wandbDir := fs.Arg(0)
	if wandbDir == "" {
		fmt.Fprintln(os.Stderr, "Error: wandb directory path required")
		fs.Usage()
		return exitCodeErrorArgs
	}

	for {
		m := leet.NewModel(leet.ModelParams{
			WandbDir: wandbDir,
			RunFile:  *runFile,
			Logger:   logger,
		})
		program := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())

		finalModel, err := program.Run()
		if err != nil {
			logger.CaptureError(fmt.Errorf("wandb-leet: %v", err))
			return exitCodeErrorInternal
		}

		// If the model requests a restart, loop again.
		if fm, ok := finalModel.(*leet.Model); ok && fm.ShouldRestart() {
			continue
		}

		return exitCodeSuccess
	}
}

// startPprofServer starts an HTTP server exposing the standard /debug/pprof/* endpoints.
//
// For safety, prefer binding explicitly to loopback (e.g. 127.0.0.1:6060) instead of ":6060".
func startPprofServer(
	addr string,
	blockRate, mutexFraction int,
) (shutdown func(context.Context) error, url string, err error) {
	if addr == "" {
		return nil, "", nil
	}
	if blockRate > 0 {
		runtime.SetBlockProfileRate(blockRate)
	}
	if mutexFraction > 0 {
		runtime.SetMutexProfileFraction(mutexFraction)
	}

	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, "", fmt.Errorf("listen %q: %w", addr, err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/debug/pprof/", pprof.Index)
	mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
	mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
	mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
	mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
	// Explicit handlers so the common endpoints show up even if index routing changes.
	mux.Handle("/debug/pprof/allocs", pprof.Handler("allocs"))
	mux.Handle("/debug/pprof/block", pprof.Handler("block"))
	mux.Handle("/debug/pprof/goroutine", pprof.Handler("goroutine"))
	mux.Handle("/debug/pprof/heap", pprof.Handler("heap"))
	mux.Handle("/debug/pprof/mutex", pprof.Handler("mutex"))
	mux.Handle("/debug/pprof/threadcreate", pprof.Handler("threadcreate"))

	srv := &http.Server{
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		serveErr := srv.Serve(ln)
		if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
			fmt.Fprintln(os.Stderr, "pprof: server error:", serveErr)
		}
	}()

	return srv.Shutdown, "http://" + ln.Addr().String() + "/debug/pprof/", nil
}
