// Command wandb-core provides the W&B SDK core service, the "leet" terminal UI
// and the "mcp" server in a single binary. The default mode runs the core
// service; the `leet` subcommand launches the local TUI for inspecting a run
// and the `mcp` subcommand serves runs to an MCP client over stdio.
//
// Usage:
//
//	wandb-core [service flags]
//	wandb-core leet [<command>] [flags] [<wandb-directory>]
//	wandb-core mcp [flags]
//
// Service flags: see `wandb-core -h`.
// Leet commands: see `wandb-core leet -h`.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/mattn/go-isatty"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/leetmcp"
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
	if len(args) > 0 {
		switch args[0] {
		case "leet":
			return leetMain(args[1:])
		case "mcp":
			return mcpMain(args[1:])
		}
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
	switch {
	case errors.Is(err, flag.ErrHelp):
		return exitCodeSuccess
	case err != nil && cmd != nil && cmd.script:
		leet.WriteQueryError(os.Stderr, &leet.QueryError{Code: "bad_request", Message: err.Error()})
		return exitCodeErrorInternal
	case err != nil:
		return exitCodeErrorArgs
	}

	pprofStop, err := startLeetPprof(opts.pprofAddr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "pprof:", err)
		return exitCodeErrorArgs
	}
	defer stopLeetPprof(pprofStop)

	recorder, stopTelemetry := leet.ConfigureTelemetry(leet.TelemetryParams{
		Disabled: opts.disableAnalytics || cmd.noTelemetry,
		Mode:     cmd.mode,
		Commit:   commit,
		BaseURL:  opts.baseURL,
	})
	defer stopTelemetry()

	logLevel := opts.logLevel
	if cmd.script {
		logLevel = 0
	}
	logger, closeLogger, err := newLeetLogger(logLevel, recorder, leet.DebugLogPath())
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

// mcpMain serves the wandb leet query verbs as MCP tools on stdin and
// stdout until stdin ends.
func mcpMain(args []string) int {
	opts := &leetOptions{}
	fs := flag.NewFlagSet("mcp", flag.ContinueOnError)
	bindLeetCommonFlags(fs, opts)
	printTools := fs.Bool("print-tools", false,
		"Print the tools as the result of tools/list and exit.")
	var appURLs []string
	fs.Func("app-urls",
		"URL prefixes of the W&B app pages of the server at --base-url, which its"+
			" URLs may start with, e.g. https://wandb.ai. Comma-separated.",
		appendKeys(&appURLs))
	fs.Usage = func() {
		fmt.Fprint(fs.Output(), "Serve W&B runs to an MCP client over stdio.\n\n"+
			"Usage:\n  wandb-core mcp [flags]\n\nFlags:\n")
		fs.PrintDefaults()
	}
	switch err := fs.Parse(args); {
	case errors.Is(err, flag.ErrHelp):
		return exitCodeSuccess
	case err != nil:
		return exitCodeErrorArgs
	case fs.NArg() > 0:
		fmt.Fprintf(os.Stderr, "Error: unexpected argument %q\n", fs.Arg(0))
		fs.Usage()
		return exitCodeErrorArgs
	}

	if *printTools {
		enc := json.NewEncoder(os.Stdout)
		enc.SetEscapeHTML(false)
		enc.SetIndent("", "  ")
		if err := enc.Encode(leetmcp.ListTools(true)); err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			return exitCodeErrorInternal
		}
		return exitCodeSuccess
	}

	pprofStop, err := startLeetPprof(opts.pprofAddr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "pprof:", err)
		return exitCodeErrorArgs
	}
	defer stopLeetPprof(pprofStop)

	recorder, stopTelemetry := leet.ConfigureTelemetry(leet.TelemetryParams{
		Disabled: opts.disableAnalytics,
		Mode:     "mcp",
		Commit:   commit,
		BaseURL:  opts.baseURL,
	})
	defer stopTelemetry()

	logger, closeLogger, err := newLeetLogger(opts.logLevel, recorder,
		filepath.Join(filepath.Dir(leet.DebugLogPath()), "wandb-mcp.debug.log"))
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return exitCodeErrorInternal
	}
	defer closeLogger()
	analytics.ConfigureOTelErrorHandler(logger.Logger)
	slog.SetDefault(logger.Logger)

	err = leetmcp.Serve(os.Stdin, os.Stdout, os.Stderr, opts.baseURL, appURLs)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
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

	// run selects a run in the wandb directory for the query commands.
	run string

	// request is the JSON-RPC request wandb-core leet session sends.
	request      string
	runs         leet.RunsQuery
	history      leet.HistoryQuery
	summaryQuery leet.SummaryQuery
	console      leet.ConsoleQuery
	system       leet.SystemQuery

	// remoteURL is the W&B URL of the project or run to open
	// (e.g. https://api.forge.coreweave.com/<entity>/<project> or
	// https://api.forge.coreweave.com/<entity>/<project>/runs/<run-id>).
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

	// script marks a command for scripts and agents: its errors are JSON
	// lines with exit code 1, and it never writes the debug log.
	script bool

	// noTelemetry marks a command that reports no launch or session telemetry.
	noTelemetry bool

	bindFlags func(fs *flag.FlagSet, opts *leetOptions)
	validate  func(opts *leetOptions) error
	run       func(opts *leetOptions, logger *observability.CoreLogger) int
}

// leetCommands lists the leet commands. The first one is the default.
var leetCommands = []*leetCommand{
	{
		name:      "run",
		args:      "<wandb-directory>",
		short:     "View the runs in a wandb directory or a W&B project, or a single run",
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
		name:      "runs",
		args:      "[<wandb-directory>]",
		short:     "List the runs of a wandb directory or a W&B project as JSON",
		mode:      "runs",
		script:    true,
		bindFlags: bindLeetRunsFlags,
		validate:  validateLeetQuerySource,
		run:       runLeetRuns,
	},
	{
		name:      "history",
		args:      "[<wandb-directory>]",
		short:     "Print the metric series of a run as JSON",
		mode:      "history",
		script:    true,
		bindFlags: bindLeetHistoryFlags,
		validate:  validateLeetQuerySource,
		run:       runLeetHistory,
	},
	{
		name:      "summary",
		args:      "[<wandb-directory>]",
		short:     "Print a run's state, latest metrics, config and console tail as JSON",
		mode:      "summary",
		script:    true,
		bindFlags: bindLeetSummaryFlags,
		validate:  validateLeetQuerySource,
		run:       runLeetSummary,
	},
	{
		name:      "console",
		args:      "[<wandb-directory>]",
		short:     "Print the console output of a run as JSON",
		mode:      "console",
		script:    true,
		bindFlags: bindLeetConsoleFlags,
		validate:  validateLeetQuerySource,
		run:       runLeetConsole,
	},
	{
		name:      "system",
		args:      "[<wandb-directory>]",
		short:     "Print the system metrics of a run as JSON",
		mode:      "system",
		script:    true,
		bindFlags: bindLeetSystemFlags,
		validate:  validateLeetQuerySource,
		run:       runLeetSystem,
	},
	{
		name:        "session",
		args:        "<wandb-directory>",
		short:       "Send a request to the LEET showing a wandb directory",
		mode:        "session",
		script:      true,
		noTelemetry: true,
		bindFlags:   bindLeetSessionFlags,
		validate:    validateLeetSessionOptions,
		run:         runLeetSession,
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
	if cmd.script {
		fs.SetOutput(io.Discard)
	}

	if err := fs.Parse(args); err != nil {
		if cmd.script && errors.Is(err, flag.ErrHelp) {
			fs.SetOutput(os.Stderr)
			fs.Usage()
		}
		return cmd, nil, err
	}

	if err := validateLeetArgs(fs, cmd, opts); err != nil {
		if !cmd.script {
			fmt.Fprintln(os.Stderr, "Error:", err)
			fs.Usage()
		}
		return cmd, nil, err
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
	fmt.Fprintf(fs.Output(), "%s\n\nUsage:\n  %s\n\nFlags:\n", cmd.short,
		strings.TrimSpace("wandb-core leet "+cmd.name+" [flags] "+cmd.args))
	fs.PrintDefaults()
}

func bindLeetCommonFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.IntVar(
		&opts.logLevel,
		"log-level",
		0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error."+
			" Debug logs are written next to the LEET config file.",
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
		"URL of the W&B server to upload telemetry to; wandb-core mcp also reads"+
			" the W&B URLs of this server. Defaults to the public W&B API.",
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
		"URL of a W&B project or run to open"+
			" (e.g. https://api.forge.coreweave.com/<entity>/<project> or"+
			" https://api.forge.coreweave.com/<entity>/<project>/runs/<run-id>).",
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

// bindLeetQueryFlags binds the flags that select the run of a query command.
func bindLeetQueryFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.StringVar(
		&opts.runFile,
		"run-file",
		"",
		"Path to the .wandb file to read."+
			" Defaults to the newest run in the wandb directory.",
	)
	fs.StringVar(&opts.run, "run", "", leet.RunDoc)
	fs.StringVar(
		&opts.remoteURL,
		"remote-url",
		"",
		"W&B URL of the run, https://<host>/<entity>/<project>/runs/<id>,"+
			" instead of a local file.",
	)
}

func bindLeetRunsFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.StringVar(&opts.runFile, "run-file", "", "Path to a .wandb file, to list only its run.")
	fs.StringVar(
		&opts.remoteURL,
		"remote-url",
		"",
		"W&B URL of the project, https://<host>/<entity>/<project>,"+
			" instead of a local directory.",
	)
	bindQueryOptions(fs, &opts.runs)
}

func bindLeetHistoryFlags(fs *flag.FlagSet, opts *leetOptions) {
	bindLeetQueryFlags(fs, opts)
	opts.history.IdleTimeout = leet.RunCrashTimeout
	bindQueryOptions(fs, &opts.history)
}

func bindLeetSummaryFlags(fs *flag.FlagSet, opts *leetOptions) {
	bindLeetQueryFlags(fs, opts)
	bindQueryOptions(fs, &opts.summaryQuery)
}

func bindLeetConsoleFlags(fs *flag.FlagSet, opts *leetOptions) {
	bindLeetQueryFlags(fs, opts)
	opts.console.IdleTimeout = leet.RunCrashTimeout
	bindQueryOptions(fs, &opts.console)
}

func bindLeetSystemFlags(fs *flag.FlagSet, opts *leetOptions) {
	bindLeetQueryFlags(fs, opts)
	bindQueryOptions(fs, &opts.system)
}

// bindQueryOptions binds a flag to each field of the query options struct
// q points to, named after the field's json name with dashes for
// underscores, documented by its doc tag and defaulting to its value.
func bindQueryOptions(fs *flag.FlagSet, q any) {
	v := reflect.ValueOf(q).Elem()
	for i := range v.NumField() {
		f := v.Type().Field(i)
		name, _, _ := strings.Cut(f.Tag.Get("json"), ",")
		name = strings.ReplaceAll(name, "_", "-")
		doc := f.Tag.Get("doc")
		switch p := v.Field(i).Addr().Interface().(type) {
		case *string:
			fs.StringVar(p, name, *p, doc)
		case *bool:
			fs.BoolVar(p, name, *p, doc)
		case *int:
			fs.IntVar(p, name, *p, doc)
		case *time.Duration:
			fs.DurationVar(p, name, *p, doc)
		case *[]string:
			fs.Func(name, doc+" Comma-separated.", appendKeys(p))
		case **int64:
			fs.Func(name, doc, setInt64(p))
		default:
			panic(fmt.Sprintf("no flag for %s %s", f.Name, f.Type))
		}
	}
}

// appendKeys returns a flag function that appends the comma-separated keys
// in its argument to keys.
func appendKeys(keys *[]string) func(string) error {
	return func(s string) error {
		for _, k := range strings.Split(s, ",") {
			if k = strings.TrimSpace(k); k != "" {
				*keys = append(*keys, k)
			}
		}
		return nil
	}
}

func setInt64(p **int64) func(string) error {
	return func(s string) error {
		v, err := strconv.ParseInt(s, 10, 64)
		*p = &v
		return err
	}
}

func bindLeetSessionFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.StringVar(&opts.request, "request", "",
		`The JSON-RPC request to send, e.g. '{"jsonrpc":"2.0","id":1,"method":"status"}'.`)
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

func validateLeetQuerySource(opts *leetOptions) error {
	switch {
	case opts.remoteURL != "" && (opts.wandbDir != "" || opts.runFile != "" || opts.run != ""):
		return errors.New(
			"--remote-url cannot be used with a wandb directory, --run-file or --run")
	case opts.remoteURL != "":
		var err error
		opts.remoteRun, err = leet.ParseRemoteURL(opts.remoteURL)
		return err
	case opts.wandbDir == "" && opts.runFile == "":
		return errors.New("wandb directory path or --run-file required")
	case opts.runFile != "" && opts.run != "":
		return errors.New("--run cannot be used with --run-file")
	default:
		return nil
	}
}

func validateLeetSessionOptions(opts *leetOptions) error {
	switch {
	case opts.wandbDir == "":
		return errors.New("wandb directory path required")
	case opts.request == "":
		return errors.New("--request required")
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

// newLeetLogger returns a logger that writes to the file at debugLogPath
// with --log-level -4 and discards its logs otherwise.
func newLeetLogger(
	logLevel int,
	recorder *analytics.TelemetryRecorder,
	debugLogPath string,
) (*observability.CoreLogger, func(), error) {
	logWriter := io.Discard
	closeLogWriter := func() {}

	// TODO: Create a log file not only if debug logging is requested.
	if logLevel == -4 {
		loggerFile, err := os.OpenFile(
			debugLogPath,
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

// queryExit reports a query's error as a JSON line and returns its exit code.
func queryExit(err error) int {
	if err != nil {
		leet.WriteQueryError(os.Stderr, err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

func runLeetRuns(opts *leetOptions, _ *observability.CoreLogger) int {
	if opts.remoteRun != nil {
		return queryExit(leet.ListRemoteRuns(opts.remoteRun, opts.runs, os.Stdout))
	}
	return queryExit(leet.ListRuns(opts.wandbDir, opts.runFile, opts.runs, os.Stdout))
}

func runLeetHistory(opts *leetOptions, _ *observability.CoreLogger) int {
	if opts.remoteRun != nil {
		return queryExit(leet.ErrRemoteNotAvailable)
	}
	return queryExit(
		leet.QueryHistory(opts.wandbDir, opts.runFile, opts.run, opts.history, os.Stdout))
}

func runLeetSummary(opts *leetOptions, _ *observability.CoreLogger) int {
	if opts.remoteRun != nil {
		return queryExit(leet.QueryRemoteSummary(opts.remoteRun, opts.summaryQuery, os.Stdout))
	}
	return queryExit(
		leet.QuerySummary(opts.wandbDir, opts.runFile, opts.run, opts.summaryQuery, os.Stdout))
}

func runLeetConsole(opts *leetOptions, _ *observability.CoreLogger) int {
	if opts.remoteRun != nil {
		return queryExit(leet.QueryRemoteConsole(opts.remoteRun, opts.console, os.Stdout))
	}
	return queryExit(
		leet.QueryConsole(opts.wandbDir, opts.runFile, opts.run, opts.console, os.Stdout))
}

func runLeetSystem(opts *leetOptions, _ *observability.CoreLogger) int {
	if opts.remoteRun != nil {
		return queryExit(leet.ErrRemoteNotAvailable)
	}
	return queryExit(
		leet.QuerySystem(opts.wandbDir, opts.runFile, opts.run, opts.system, os.Stdout))
}

// runLeetSession prints the reply of the running LEET. A reply that carries
// an error is printed as is and exits 1.
func runLeetSession(opts *leetOptions, _ *observability.CoreLogger) int {
	err := leet.SessionRequest(opts.wandbDir, opts.request, os.Stdout)
	switch {
	case err == nil:
		return exitCodeSuccess
	case !errors.Is(err, leet.ErrSessionReplyError):
		leet.WriteQueryError(os.Stderr, err)
	}
	return exitCodeErrorInternal
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
	var control chan leet.ControlMsg
	if opts.remoteRun == nil {
		control = make(chan leet.ControlMsg)
		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan struct{})
		go func() {
			defer close(done)
			leet.ServeControl(ctx, opts.wandbDir, control, logger)
		}()
		defer func() {
			cancel()
			<-done
		}()
	}

	for {
		params, err := newModelParams(opts, logger)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			return exitCodeErrorArgs
		}
		params.Control = control
		m := leet.NewModel(params)
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

func newModelParams(
	opts *leetOptions,
	logger *observability.CoreLogger,
) (leet.ModelParams, error) {
	params := leet.ModelParams{Logger: logger}

	if opts.remoteRun == nil {
		params.Backend = leet.NewLocalWorkspaceBackend(opts.wandbDir, logger)
		if opts.runFile != "" {
			params.RunParams = &leet.RunParams{RunFile: opts.runFile}
		}
		return params, nil
	}

	backend, err := leet.NewRemoteWorkspaceBackend(
		opts.remoteRun.BaseURL,
		opts.remoteRun.Entity,
		opts.remoteRun.Project,
		logger,
	)
	if err != nil {
		return params, err
	}
	params.Backend = backend
	if opts.remoteRun.RunID != "" {
		params.RunParams = &leet.RunParams{Remote: opts.remoteRun}
	}
	return params, nil
}
