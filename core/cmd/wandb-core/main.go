// Command wandb-core provides the W&B SDK core service and the "leet" terminal UI
// in a single binary. The default mode runs the core service; the `leet` subcommand
// launches the local TUI for inspecting a run.
//
// Usage:
//
//	wandb-core [service flags]
//	wandb-core leet [<run-directory>] [leet flags]
//
// Service flags: see `wandb-core -h`.
// Leet flags:    see `wandb-core leet -h`.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/nfs"
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
	if len(args) > 0 {
		switch args[0] {
		case "leet":
			return leetMain(args[1:])
		case "nfs":
			return nfsMain(args[1:])
		}
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

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, `wandb-core leet - Lightweight Experiment Exploration Tool
A terminal UI for viewing your W&B runs locally.

Usage:
  wandb-core leet [flags] <wandb-file>
Arguments:
  <wandb-file>       Path to the .wandb file of a W&B run.
                     Example:
                       /path/to/.wandb/run-20250731_170606-iazb7i1k/run-iazb7i1k.wandb

Options:
  -h, --help         Show this help message

Flags:
`)
		fs.PrintDefaults()
	}

	err := fs.Parse(args)
	if err == flag.ErrHelp {
		return exitCodeSuccess
	}
	if err != nil {
		return exitCodeErrorArgs
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

	wandbFile := fs.Arg(0)

	// Run the TUI; allow in-process restarts (Alt+R) without re-parsing flags.
	for {
		model := leet.NewModel(wandbFile, nil, logger)
		p := tea.NewProgram(model, tea.WithAltScreen(), tea.WithMouseCellMotion())

		finalModel, err := p.Run()
		if err != nil {
			logger.CaptureError(fmt.Errorf("wandb-leet: %v", err))
			return exitCodeErrorInternal
		}

		// If the model requests a restart, loop again.
		if m, ok := finalModel.(*leet.Model); ok && m.ShouldRestart() {
			continue
		}

		return exitCodeSuccess
	}
}

// nfsMain runs the NFS subcommand for listing artifacts and runs.
func nfsMain(args []string) int {
	fs := flag.NewFlagSet("nfs", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, `wandb-core nfs - NFS server for W&B artifacts

Usage:
  wandb-core nfs ls <entity>/<project>
  wandb-core nfs serve [--listen :2049] <entity>/<project>

Commands:
  ls      List artifacts in a project
  serve   Start NFS server to browse artifacts

Environment Variables:
  WANDB_API_KEY   - Your W&B API key (required)
  WANDB_BASE_URL  - W&B API base URL (default: https://api.wandb.ai)

Examples:
  wandb-core nfs ls my-team/my-project
  wandb-core nfs serve my-team/my-project
  wandb-core nfs serve --listen :3049 my-team/my-project

`)
	}

	err := fs.Parse(args)
	if err == flag.ErrHelp {
		return exitCodeSuccess
	}
	if err != nil {
		return exitCodeErrorArgs
	}

	if fs.NArg() < 1 {
		fs.Usage()
		return exitCodeErrorArgs
	}

	subCmd := fs.Arg(0)
	switch subCmd {
	case "ls":
		if fs.NArg() < 2 {
			fmt.Fprintln(os.Stderr, "Error: missing project path (entity/project)")
			return exitCodeErrorArgs
		}
		return nfsLs(fs.Arg(1))
	case "serve":
		return nfsServe(fs.Args()[1:])
	default:
		fmt.Fprintf(os.Stderr, "Error: unknown nfs subcommand: %s\n", subCmd)
		return exitCodeErrorArgs
	}
}

func nfsLs(projectPath string) int {
	cfg, err := nfs.LoadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return exitCodeErrorInternal
	}

	client, err := nfs.NewGraphQLClient(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error creating GraphQL client: %v\n", err)
		return exitCodeErrorInternal
	}

	path, err := nfs.ParseProjectPath(projectPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return exitCodeErrorArgs
	}

	lister := nfs.NewLister(client)
	collections, err := lister.ListCollections(context.Background(), path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return exitCodeErrorInternal
	}

	nfs.PrintCollections(os.Stdout, collections)
	return exitCodeSuccess
}

func nfsServe(args []string) int {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	listen := fs.String("listen", ":2049", "Listen address for NFS server")

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, `wandb-core nfs serve - Start NFS server for W&B artifacts

Usage:
  wandb-core nfs serve [--listen :2049] <entity>/<project>

Flags:
  --listen   Listen address (default: :2049)

Examples:
  wandb-core nfs serve my-team/my-project
  wandb-core nfs serve --listen :3049 my-team/my-project

Mount the NFS share (macOS):
  mkdir -p /tmp/wandb-mount
  sudo mount -t nfs -o vers=4,port=2049 localhost:/ /tmp/wandb-mount

`)
	}

	err := fs.Parse(args)
	if err == flag.ErrHelp {
		return exitCodeSuccess
	}
	if err != nil {
		return exitCodeErrorArgs
	}

	if fs.NArg() < 1 {
		fmt.Fprintln(os.Stderr, "Error: missing project path (entity/project)")
		fs.Usage()
		return exitCodeErrorArgs
	}

	projectPath := fs.Arg(0)
	path, err := nfs.ParseProjectPath(projectPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return exitCodeErrorArgs
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		fmt.Fprintln(os.Stderr, "\nReceived shutdown signal")
		cancel()
	}()

	opts := nfs.ServeOptions{
		ListenAddr:  *listen,
		ProjectPath: path,
	}

	if err := nfs.Serve(ctx, opts); err != nil && err != context.Canceled {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return exitCodeErrorInternal
	}

	return exitCodeSuccess
}
