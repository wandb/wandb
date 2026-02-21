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
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/getsentry/sentry-go"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pprof"
	"github.com/wandb/wandb/core/internal/processlib"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/server"
)

// commit hash is set by the build script.
var commit string

const (
	exitCodeSuccess       = 0 // normal exit
	exitCodeErrorInternal = 1 // some error occurred
	exitCodeErrorArgs     = 2 // incorrect command-line flags

	defaultDetachedIdleTimeout = 10 * time.Minute

	// exitCodeSignal is used when the program shuts down due to a signal.
	//
	// A common convention is to use 128 plus the signal number, but Go's
	// signal package does not provide the standard integer numbers associated
	// with the signal, so for simplicity, we return 128.
	// See https://github.com/golang/go/issues/30328.
	exitCodeSignal = 128
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
		"Specifies the filename where the server will write the port number it uses to"+
			" communicate with clients.")
	pid := flag.Int("pid", 0,
		"Specifies the process ID (PID) of the external process that spins up this service.")
	detached := flag.Bool(
		"detached",
		false,
		"Run the service detached from its parent process. In detached mode,"+
			" the service does not automatically exit when the parent process exits.",
	)
	idleTimeout := flag.Duration(
		"idle-timeout",
		defaultDetachedIdleTimeout,
		"If --detached is set, shut down the service after this much idle time"+
			" with no connected clients. 0 disables the idle shutdown.",
	)
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

	if *idleTimeout < 0 {
		fmt.Fprintln(os.Stderr, "Error: --idle-timeout must be >= 0")
		return exitCodeErrorArgs
	}

	var shutdownOnParentExitEnabled bool
	if *pid != 0 && *enableOsPidShutdown && !*detached {
		shutdownOnParentExitEnabled = processlib.ShutdownOnParentExit(*pid)
	}

	// Sentry (disabled if --no-observability)
	var sentryDSN string
	if !*disableAnalytics {
		sentryDSN = observability.WandbCoreDSN
	}
	err := sentry.Init(sentry.ClientOptions{
		Dsn:              sentryDSN,
		AttachStacktrace: true,
		Release:          version.Version,
		Dist:             commit,
		Environment:      version.Environment,
	})
	if err != nil {
		slog.Error("main: failed to init Sentry", "error", err)
	} else {
		defer sentry.Flush(2 * time.Second)
	}

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
			"detached", *detached,
			"idle-timeout", *idleTimeout,
			"log-level", *logLevel,
			"disable-analytics", *disableAnalytics,
			"shutdown-on-parent-exit", shutdownOnParentExitEnabled,
			"enable-dcgm-profiling", *enableDCGMProfiling,
		)
		loggerPath = file.Name()
		defer func() { _ = file.Close() }()
	}

	// Record certain signals in the log file for debugging.
	signalCh := make(chan os.Signal, 1)
	signal.Notify(signalCh, syscall.SIGINT, syscall.SIGTERM)

	srv := server.NewServer(
		server.ServerParams{
			Commit:              commit,
			EnableDCGMProfiling: *enableDCGMProfiling,
			ListenOnLocalhost:   *listenOnLocalhost,
			LoggerPath:          loggerPath,
			LogLevel:            slog.Level(*logLevel),
			ParentPID:           *pid,
			Detached:            *detached,
			IdleTimeout:         *idleTimeout,
		},
	)
	srvCh := make(chan error, 1)
	go func() { srvCh <- srv.Serve(*portFilename) }()

	select {
	case err := <-srvCh:
		if err != nil {
			slog.Error("main: Serve() returned error", "error", err)
			return exitCodeErrorInternal
		} else {
			return exitCodeSuccess
		}

	case sig := <-signalCh:
		slog.Info("main: received shutdown signal", "signal", sig)
		return exitCodeSignal
	}
}

// leetMain runs the TUI subcommand.
func leetMain(args []string) int {
	opts, err := parseLeetOptions(args)
	if err != nil {
		if err == flag.ErrHelp {
			return exitCodeSuccess
		}
		return exitCodeErrorArgs
	}

	pprofStop, err := startLeetPprof(opts.pprofAddr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "pprof:", err)
		return exitCodeErrorArgs
	}
	defer stopLeetPprof(pprofStop)

	flushSentry := configureLeetSentry(opts.disableAnalytics, leetSentryMessage(opts))
	defer flushSentry()

	logger, closeLogger, err := newLeetLogger(opts.logLevel)
	if err != nil {
		fmt.Println("fatal:", err)
		return exitCodeErrorInternal
	}
	defer closeLogger()

	return runLeetCommand(opts, logger)
}

type leetOptions struct {
	logLevel         int
	disableAnalytics bool
	runFile          string
	pprofAddr        string
	editConfig       bool
	symonMode        bool
	symonInterval    time.Duration
	wandbDir         string
	
	baseUrl          string
	entity           string
	project          string
	runId            string
}

func parseLeetOptions(args []string) (leetOptions, error) {
	var opts leetOptions

	fs := flag.NewFlagSet("leet", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	bindLeetFlags(fs, &opts)
	fs.Usage = func() { printLeetUsage(fs) }

	if err := fs.Parse(args); err != nil {
		return leetOptions{}, err
	}

	opts.wandbDir = fs.Arg(0)
	if err := validateLeetOptions(fs, opts); err != nil {
		return leetOptions{}, err
	}

	return opts, nil
}

func bindLeetFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.IntVar(
		&opts.logLevel,
		"log-level",
		0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.",
	)
	fs.BoolVar(
		&opts.disableAnalytics,
		"no-observability",
		false,
		"Disables observability features such as metrics and logging analytics.",
	)
	fs.StringVar(
		&opts.runFile,
		"run-file",
		"",
		"Path to a .wandb file to open directly in single-run view.",
	)
	fs.StringVar(
		&opts.pprofAddr,
		"pprof",
		"",
		"If set, serves /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
	)
	fs.BoolVar(&opts.editConfig, "config", false, "Open config editor.")
	fs.BoolVar(&opts.symonMode, "symon", false, "Launch standalone system metrics mode.")
	fs.DurationVar(
		&opts.symonInterval,
		"interval",
		leet.DefaultSymonSamplingInterval,
		"Sampling interval for standalone system metrics (e.g. 500ms, 2s, 1m).",
	)
	fs.StringVar(
		&opts.baseUrl,
		"base-url",
		"",
		"Specifies the base URL of the W&B server for querying remote runs.",
	)
	fs.StringVar(
		&opts.entity,
		"entity",
		"",
		"Specifies the entity who owns the run.",
	)
	fs.StringVar(
		&opts.project,
		"project",
		"",
		"Specifies the project the remote run belongs to.",
	)
	fs.StringVar(
		&opts.runId,
		"run-id",
		"",
		"Specifies the run ID of the remote run.",
	)
}

func printLeetUsage(fs *flag.FlagSet) {
	fmt.Fprintf(os.Stderr, `wandb-core leet - Lightweight Experiment Exploration Tool
A terminal UI for viewing your W&B runs locally.

Usage:
  wandb-core leet [flags] <wandb-directory>
  wandb-core leet --config
  wandb-core leet --symon [flags]
  wandb-core leet [flags] <wandb-file/wandb-run-path>

Arguments:
  <wandb-file> Path to the .wandb file of a W&B run or a W&B run path.
		Example:
		  /path/to/.wandb/run-20250731_170606-iazb7i1k/run-iazb7i1k.wandb
	If

Options:
  -h, --help         Show this help message
Flags:
`)
	fs.PrintDefaults()
}

func validateLeetOptions(fs *flag.FlagSet, opts leetOptions) error {
	switch {
	case opts.symonInterval <= 0:
		fmt.Fprintln(os.Stderr, "Error: --interval must be > 0")
		fs.Usage()
		return fmt.Errorf("invalid interval %v", opts.symonInterval)
	case opts.symonMode && fs.NArg() != 0:
		fmt.Fprintln(os.Stderr, "Error: --symon does not take a wandb directory")
		fs.Usage()
		return fmt.Errorf("unexpected wandb directory %q in symon mode", fs.Arg(0))
	case !opts.editConfig && !opts.symonMode && opts.wandbDir == "" && opts.baseUrl == "":
		fmt.Fprintln(os.Stderr, "Error: wandb directory path required")
		fs.Usage()
		return fmt.Errorf("wandb directory path required")
	default:
		return nil
	}
}

func startLeetPprof(addr string) (func(context.Context) error, error) {
	return pprof.StartServer(addr)
}

func stopLeetPprof(pprofStop func(context.Context) error) {
	if pprofStop == nil {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = pprofStop(ctx)
}

func configureLeetSentry(disableAnalytics bool, message string) func() {
	var sentryDSN string
	if !disableAnalytics {
		sentryDSN = observability.LeetSentryDSN
	}

	err := sentry.Init(sentry.ClientOptions{
		Dsn:              sentryDSN,
		AttachStacktrace: true,
		Release:          version.Version,
		Dist:             commit,
		Environment:      version.Environment,
	})
	if err != nil {
		slog.Error("main: failed to init Sentry", "error", err)
		return func() {}
	}

	sentry.CaptureMessage(message)
	return func() { sentry.Flush(2 * time.Second) }
}

func leetSentryMessage(opts leetOptions) string {
	switch {
	case opts.editConfig:
		return "wandb-leet-config"
	case opts.symonMode:
		return "wandb-symon"
	default:
		return "wandb-leet"
	}
}

func newLeetLogger(logLevel int) (*observability.CoreLogger, func(), error) {
	logWriter := io.Discard
	closeLogWriter := func() {}

	// TODO: Create a log file not only if debug logging is requested.
	if logLevel == -4 {
		loggerFile, err := os.OpenFile(
			"wandb-leet.debug.log",
			os.O_WRONLY|os.O_CREATE|os.O_TRUNC,
			0o644,
		)
		if err != nil {
			return nil, nil, err
		}
		logWriter = loggerFile
		closeLogWriter = func() { _ = loggerFile.Close() }
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			logWriter,
			&slog.HandlerOptions{Level: slog.Level(logLevel)},
		)),
		observability.NewSentryContext(sentry.CurrentHub()),
	)
	return logger, closeLogWriter, nil
}

func runLeetCommand(opts leetOptions, logger *observability.CoreLogger) int {
	if opts.editConfig {
		return runLeetConfigEditor(logger)
	}
	if opts.symonMode {
		return runSymon(opts, logger)
	}
	return runLeetWorkspace(opts, logger)
}

func runLeetConfigEditor(logger *observability.CoreLogger) int {
	editor := leet.NewConfigEditor(leet.ConfigEditorParams{Logger: logger})
	program := tea.NewProgram(editor)
	if _, err := program.Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

func runSymon(opts leetOptions, logger *observability.CoreLogger) int {
	for {
		m := leet.NewSymon(leet.SymonParams{
			Logger:           logger,
			SamplingInterval: opts.symonInterval,
		})
		program := tea.NewProgram(m)

		finalModel, err := program.Run()
		m.Cleanup()
		if err != nil {
			logger.CaptureError(fmt.Errorf("wandb-symon: %v", err))
			return exitCodeErrorInternal
		}

		if fm, ok := finalModel.(*leet.Symon); ok && fm.ShouldRestart() {
			continue
		}
		return exitCodeSuccess
	}
}

func runLeetWorkspace(opts leetOptions, logger *observability.CoreLogger) int {
	var runParams *leet.RunParams
	if opts.baseUrl != "" {
		runParams = &leet.RunParams{
			RemoteRunParams: &leet.RemoteRunParams{
				BaseURL: opts.baseUrl,
				Entity:  opts.entity,
				Project: opts.project,
				RunId:   opts.runId,
			},
		}
	} else if opts.runFile != "" {
		runParams = &leet.RunParams{
			LocalRunParams: &leet.LocalRunParams{
				RunFile: opts.runFile,
			},
		}
	}

	for {
		m := leet.NewModel(leet.ModelParams{
			WandbDir:  opts.wandbDir,
			RunParams: runParams,
			Logger:    logger,
		})
		program := tea.NewProgram(m)

		finalModel, err := program.Run()
		if err != nil {
			logger.CaptureError(fmt.Errorf("wandb-leet: %v", err))
			return exitCodeErrorInternal
		}

		if fm, ok := finalModel.(*leet.Model); ok && fm.ShouldRestart() {
			continue
		}
		return exitCodeSuccess
	}
}
