// Command wandb-core provides the W&B SDK core service and the "leet" terminal UI
// in a single binary. The default mode runs the core service; the `leet` subcommand
// launches the local TUI for inspecting a run.
//
// Usage:
//
//	wandb-core [service flags]
//	wandb-core leet [<command>] [flags] [<wandb-directory>]
//
// Service flags: see `wandb-core -h`.
// Leet commands: see `wandb-core leet -h`.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/mattn/go-isatty"

	"github.com/wandb/wandb/core/internal/analytics"
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

	// Datadog telemetry is disabled if --no-observability.
	if *disableAnalytics {
		analytics.Disable()
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

	analytics.ConfigureOTelErrorHandler(slog.Default())

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

	for {
		select {
		case err := <-srvCh:
			switch {
			case err != nil:
				slog.Error("main: Serve() returned error", "error", err)
				return exitCodeErrorInternal
			default:
				return exitCodeSuccess
			}
		case sig := <-signalCh:
			slog.Info("main: received shutdown signal", "signal", sig)
			srv.ForceStop()
			if err := <-srvCh; err != nil {
				slog.Error("main: Serve() returned error", "error", err)
			}
			return exitCodeSignal
		}
	}
}

// leetMain runs a LEET command.
func leetMain(args []string) int {
	cmd, opts, err := parseLeetArgs(args)
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

	recorder, stopTelemetry := leet.ConfigureTelemetry(leet.TelemetryParams{
		Disabled: opts.disableAnalytics,
		Mode:     cmd.mode,
		Commit:   commit,
		BaseURL:  opts.baseURL,
	})
	defer stopTelemetry()

	logger, closeLogger, err := newLeetLogger(opts.logLevel, recorder)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return exitCodeErrorInternal
	}
	defer closeLogger()

	analytics.ConfigureOTelErrorHandler(logger.Logger)
	logger.RecordTelemetry("leet_launch", nil)

	started := time.Now()
	exitCode := cmd.run(opts, logger)
	duration := time.Since(started)
	recorder.RecordHistogram(
		context.Background(),
		"leet_session_duration",
		duration.Seconds(),
		&analytics.LowCardinalityAttributes{},
	)

	sessionAttributes := leet.SessionAttributes()
	sessionAttributes["duration_seconds"] = strconv.FormatInt(
		int64(duration/time.Second), 10)
	sessionAttributes["exit_code"] = strconv.Itoa(exitCode)
	logger.RecordTelemetry("leet_session", sessionAttributes)
	return exitCode
}

type leetOptions struct {
	logLevel         int
	disableAnalytics bool
	baseURL          string
	runFile          string
	pprofAddr        string
	symonInterval    time.Duration
	summary          bool
	jsonOutput       bool
	follow           bool
	idleTimeout      time.Duration
	wandbDir         string

	// remoteURL is the W&B URL of the run to open
	// (e.g. https://api.wandb.ai/<entity>/<project>/runs/<run-id>).
	// Non-empty means we are in remote mode.
	remoteURL string

	// remoteRun is the parsed remoteURL. Set during validation.
	remoteRun *leet.RemoteRunParams
}

// leetCommand is a `wandb-core leet` command. The commands mirror the
// `wandb leet` commands that run them.
type leetCommand struct {
	name  string
	args  string // positional arguments for the usage line, if any
	short string // one-line description for the command list
	mode  string // launch mode reported in telemetry

	bindFlags func(fs *flag.FlagSet, opts *leetOptions)
	validate  func(opts *leetOptions) error
	run       func(opts *leetOptions, logger *observability.CoreLogger) int
}

// leetCommands lists the leet commands. The first one is the default.
var leetCommands = []*leetCommand{
	{
		name:      "run",
		args:      "<wandb-directory>",
		short:     "View the runs in a wandb directory, a single run, or a remote run",
		mode:      "leet",
		bindFlags: bindLeetRunFlags,
		validate:  validateLeetRunOptions,
		run:       runLeetWorkspace,
	},
	{
		name:      "inspect",
		args:      "[<wandb-directory>]",
		short:     "Inspect a run's .wandb transaction log",
		mode:      "inspect",
		bindFlags: bindLeetInspectFlags,
		validate:  validateLeetInspectOptions,
		run:       runLeetInspector,
	},
	{
		name:      "symon",
		short:     "View live local system metrics",
		mode:      "symon",
		bindFlags: bindLeetSymonFlags,
		validate:  validateLeetSymonOptions,
		run:       runSymon,
	},
	{
		name:  "config",
		short: "Edit the LEET configuration",
		mode:  "config",
		run:   runLeetConfigEditor,
	},
}

// parseLeetArgs parses `wandb-core leet [<command>] [flags] [<args>]`.
func parseLeetArgs(args []string) (*leetCommand, *leetOptions, error) {
	if len(args) > 0 && slices.Contains([]string{"-h", "-help", "--help"}, args[0]) {
		printLeetUsage()
		return nil, nil, flag.ErrHelp
	}

	cmd := leetCommands[0]
	if len(args) > 0 {
		i := slices.IndexFunc(leetCommands, func(c *leetCommand) bool {
			return c.name == args[0]
		})
		if i >= 0 {
			cmd, args = leetCommands[i], args[1:]
		}
	}

	opts := &leetOptions{}
	fs := flag.NewFlagSet("leet "+cmd.name, flag.ContinueOnError)
	bindLeetCommonFlags(fs, opts)
	if cmd.bindFlags != nil {
		cmd.bindFlags(fs, opts)
	}
	fs.Usage = func() { printLeetCommandUsage(fs, cmd) }

	if err := fs.Parse(args); err != nil {
		return nil, nil, err
	}

	if err := validateLeetArgs(fs, cmd, opts); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		fs.Usage()
		return nil, nil, err
	}

	return cmd, opts, nil
}

func validateLeetArgs(fs *flag.FlagSet, cmd *leetCommand, opts *leetOptions) error {
	maxArgs := 0
	if cmd.args != "" {
		maxArgs = 1
	}
	if fs.NArg() > maxArgs {
		return fmt.Errorf("unexpected argument %q", fs.Arg(maxArgs))
	}

	opts.wandbDir = fs.Arg(0)
	if cmd.validate == nil {
		return nil
	}
	return cmd.validate(opts)
}

func printLeetUsage() {
	fmt.Fprint(os.Stderr, `wandb-core leet - Lightweight Experiment Exploration Tool
A terminal UI for viewing your W&B runs locally.

Usage:
  wandb-core leet [<command>] [flags] [<args>]

The command defaults to "run".

Commands:
`)
	for _, cmd := range leetCommands {
		fmt.Fprintf(os.Stderr, "  %-8s %s\n", cmd.name, cmd.short)
	}
	fmt.Fprint(os.Stderr, "\nRun 'wandb-core leet <command> -h' for the command's flags.\n")
}

func printLeetCommandUsage(fs *flag.FlagSet, cmd *leetCommand) {
	fmt.Fprintf(os.Stderr, "%s\n\nUsage:\n  %s\n\nFlags:\n", cmd.short,
		strings.TrimSpace("wandb-core leet "+cmd.name+" [flags] "+cmd.args))
	fs.PrintDefaults()
}

func bindLeetCommonFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.IntVar(
		&opts.logLevel,
		"log-level",
		0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error."+
			" Debug logs are written to wandb-leet.debug.log next to the LEET config file.",
	)
	fs.BoolVar(
		&opts.disableAnalytics,
		"no-observability",
		version.Environment == "development",
		"Disables observability features such as metrics and logging analytics.",
	)
	fs.StringVar(
		&opts.baseURL,
		"base-url",
		"",
		"URL of the W&B server to upload telemetry to."+
			" Defaults to the public W&B API.",
	)
	fs.StringVar(
		&opts.pprofAddr,
		"pprof",
		"",
		"If set, serves /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
	)
}

func bindLeetRunFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.StringVar(
		&opts.runFile,
		"run-file",
		"",
		"Path to a .wandb file to open directly in single-run view.",
	)
	fs.StringVar(
		&opts.remoteURL,
		"remote-url",
		"",
		"URL of a W&B run to open"+
			" (e.g. https://api.wandb.ai/<entity>/<project>/runs/<run-id>).",
	)
}

func bindLeetInspectFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.StringVar(
		&opts.runFile,
		"run-file",
		"",
		"Path to the .wandb file to inspect."+
			" Defaults to the latest run in the wandb directory.",
	)
	fs.BoolVar(
		&opts.summary,
		"summary",
		false,
		"Print the run's state, latest metric values, config and console tail"+
			" instead of its records.",
	)
	fs.BoolVar(
		&opts.jsonOutput,
		"json",
		false,
		"Print JSON: one line per record, or one object with --summary.",
	)
	fs.BoolVar(
		&opts.follow,
		"follow",
		false,
		"Keep printing records as the run writes them until it exits.",
	)
	fs.DurationVar(
		&opts.idleTimeout,
		"idle-timeout",
		leet.RunCrashTimeout,
		"With --follow, stop once the run's file has gone this long without"+
			" a write. 0 waits forever.",
	)
}

func bindLeetSymonFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.DurationVar(
		&opts.symonInterval,
		"interval",
		leet.DefaultSymonSamplingInterval,
		"Sampling interval for system metrics (e.g. 500ms, 2s, 1m).",
	)
}

func validateLeetRunOptions(opts *leetOptions) error {
	switch {
	case opts.remoteURL == "" && opts.wandbDir == "":
		return errors.New("wandb directory path or --remote-url required")
	case opts.remoteURL == "":
		return nil
	case opts.runFile != "":
		return errors.New("--run-file cannot be used with --remote-url")
	case opts.wandbDir != "":
		return errors.New("--remote-url does not take a wandb directory")
	}

	var err error
	opts.remoteRun, err = leet.ParseRemoteURL(opts.remoteURL)
	return err
}

func validateLeetInspectOptions(opts *leetOptions) error {
	switch {
	case opts.summary && opts.follow:
		return errors.New("--summary cannot be used with --follow")
	case opts.idleTimeout < 0:
		return errors.New("--idle-timeout must be >= 0")
	case opts.wandbDir == "" && opts.runFile == "":
		return errors.New("wandb directory path or --run-file required")
	default:
		return nil
	}
}

func validateLeetSymonOptions(opts *leetOptions) error {
	if opts.symonInterval <= 0 {
		return errors.New("--interval must be > 0")
	}
	return nil
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

func newLeetLogger(
	logLevel int,
	recorder *analytics.TelemetryRecorder,
) (*observability.CoreLogger, func(), error) {
	logWriter := io.Discard
	closeLogWriter := func() {}

	// TODO: Create a log file not only if debug logging is requested.
	if logLevel == -4 {
		loggerFile, err := os.OpenFile(
			leet.DebugLogPath(),
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
		recorder,
	)
	return logger, closeLogWriter, nil
}

// runLeetInspector runs the transaction log record inspector, or prints
// the run's summary or records when asked to or when stdout is not
// a terminal.
func runLeetInspector(opts *leetOptions, logger *observability.CoreLogger) int {
	var err error
	switch {
	case opts.summary:
		err = leet.PrintSummary(opts.runFile, opts.wandbDir, os.Stdout, opts.jsonOutput)
	case opts.jsonOutput || opts.follow || !stdoutIsTerminal():
		err = leet.DumpRecords(opts.runFile, opts.wandbDir, os.Stdout, os.Stderr,
			leet.DumpOptions{
				JSON:        opts.jsonOutput,
				Follow:      opts.follow,
				IdleTimeout: opts.idleTimeout,
			})
	default:
		return runLeetInspectorTUI(opts, logger)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

func runLeetInspectorTUI(opts *leetOptions, logger *observability.CoreLogger) int {
	m := leet.NewInspector(leet.InspectorParams{
		RunFile:  opts.runFile,
		WandbDir: opts.wandbDir,
		Logger:   logger,
	})
	program := tea.NewProgram(m)

	_, err := program.Run()
	m.Cleanup()
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		logger.CaptureError(
			"main",
			fmt.Errorf("wandb-leet-inspect: %v", err),
		)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

// stdoutIsTerminal reports whether stdout is attached to a terminal.
func stdoutIsTerminal() bool {
	fd := os.Stdout.Fd()
	return isatty.IsTerminal(fd) || isatty.IsCygwinTerminal(fd)
}

func runLeetConfigEditor(_ *leetOptions, logger *observability.CoreLogger) int {
	editor := leet.NewConfigEditor(leet.ConfigEditorParams{Logger: logger})
	program := tea.NewProgram(editor)
	if _, err := program.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

func runSymon(opts *leetOptions, logger *observability.CoreLogger) int {
	for {
		m := leet.NewSymon(leet.SymonParams{
			Logger:           logger,
			SamplingInterval: opts.symonInterval,
		})
		program := tea.NewProgram(m)

		finalModel, err := program.Run()
		m.Cleanup()
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			logger.CaptureError(
				"main",
				fmt.Errorf("wandb-symon: %v", err),
			)
			return exitCodeErrorInternal
		}

		if fm, ok := finalModel.(*leet.Symon); ok && fm.ShouldRestart() {
			continue
		}
		return exitCodeSuccess
	}
}

func runLeetWorkspace(opts *leetOptions, logger *observability.CoreLogger) int {
	var runParams *leet.RunParams
	if opts.remoteRun != nil {
		runParams = &leet.RunParams{Remote: opts.remoteRun}
	} else if opts.runFile != "" {
		runParams = &leet.RunParams{RunFile: opts.runFile}
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
			fmt.Fprintln(os.Stderr, "Error:", err)
			logger.CaptureError(
				"main",
				fmt.Errorf("wandb-leet: %v", err),
			)
			return exitCodeErrorInternal
		}

		if fm, ok := finalModel.(*leet.Model); ok && fm.ShouldRestart() {
			continue
		}
		return exitCodeSuccess
	}
}
