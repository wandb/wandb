// Command wandb-core provides the W&B SDK core service and the "leet" terminal UI
// in a single binary. The default mode runs the core service; the `leet` subcommand
// launches the local TUI for inspecting a run.
//
// Usage:
//
//	wandb-core [service flags]
//	wandb-core leet [<run-directory>] [leet flags]
//	wandb-core help [leet]
//
// Service flags: see `wandb-core -h`.
// Leet flags:    see `wandb-core leet -h`.
package main

import (
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/processlib"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/server"
)

// commit is set by the build script and used in service mode.
var commit string

func main() {
	os.Exit(run(os.Args[1:]))
}

type mode int

const (
	modeService mode = iota
	modeLeet
	modeHelp
)

// dispatch determines which mode to run and returns the remaining args for that mode.
func dispatch(args []string) (mode, []string) {
	if len(args) == 0 {
		return modeService, nil
	}
	switch args[0] {
	case "leet":
		return modeLeet, args[1:]
	case "help", "--help", "-h":
		if len(args) > 1 && args[1] == "leet" {
			return modeLeet, []string{"-h"}
		}
		return modeHelp, nil
	default:
		// Unknown token at top-level: let service flag parsing handle it
		return modeService, args
	}
}

func run(args []string) int {
	switch m, rest := dispatch(args); m {
	case modeLeet:
		return leetMain(rest)
	case modeHelp:
		printTopLevelUsage()
		return 0
	default:
		return serviceMain(rest)
	}
}

// printTopLevelUsage prints a concise entrypoint help, deferring details to subcommands.
func printTopLevelUsage() {
	fmt.Fprintf(os.Stderr, "wandb-core - W&B core service and tools\n\n")
	fmt.Fprintf(os.Stderr, "Usage:\n")
	fmt.Fprintf(os.Stderr, "  wandb-core [service flags]\n")
	fmt.Fprintf(os.Stderr, "  wandb-core leet [<run-directory>] [leet flags]\n")
	fmt.Fprintf(os.Stderr, "  wandb-core help [leet]\n\n")
	fmt.Fprintf(os.Stderr, "Run 'wandb-core -h' for service flags, or 'wandb-core leet -h' for Leet TUI flags.\n")
}

// serviceMain runs the default W&B SDK core service.
func serviceMain(args []string) int {
	fs := flag.NewFlagSet("wandb-core", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	portFilename := fs.String("port-filename", "port_file.txt",
		"Specifies the filename where the server will write the port number it uses to communicate with clients.")
	pid := fs.Int("pid", 0,
		"Specifies the process ID (PID) of the external process that spins up this service.")
	logLevel := fs.Int("log-level", 0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.")
	disableAnalytics := fs.Bool("no-observability", false,
		"Disables observability features such as metrics and logging analytics.")
	enableOsPidShutdown := fs.Bool("os-pid-shutdown", false,
		"Enables automatic server shutdown when the external process identified by the PID terminates.")
	enableDCGMProfiling := fs.Bool("enable-dcgm-profiling", false,
		"Enables collection of profiling metrics for Nvidia GPUs using DCGM. Requires a running `nvidia-dcgm` service.")
	listenOnLocalhost := fs.Bool("listen-on-localhost", false,
		"Whether to listen on a localhost socket. This is less secure than Unix sockets, but some clients do not support them (e.g. Python on Windows).")

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "============================================\n")
		fmt.Fprintf(os.Stderr, "      WANDB Core Service Configuration      \n")
		fmt.Fprintf(os.Stderr, "============================================\n")
		fmt.Fprintf(os.Stderr, "Version: %s\n", version.Version)
		fmt.Fprintf(os.Stderr, "Commit SHA: %s\n\n", commit)
		fmt.Fprintf(os.Stderr, "Use the following flags to configure the wandb sdk service:\n\n")
		fs.PrintDefaults()
	}

	if err := fs.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	if fs.NArg() != 0 {
		fmt.Fprintf(os.Stderr, "unexpected argument(s): %v\n\n", fs.Args())
		fs.Usage()
		return 2
	}

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
		return 1
	}
	return 0
}

// leetMain runs the TUI subcommand.
func leetMain(args []string) int {
	fs := flag.NewFlagSet("leet", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	var helpFlag bool
	fs.BoolVar(&helpFlag, "help", false, "Show help message")
	fs.BoolVar(&helpFlag, "h", false, "Show help message (shorthand)")

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "wandb-core leet - Lightweight Experiment Exploration Tool\n\n")
		fmt.Fprintf(os.Stderr, "A terminal UI for viewing your W&B runs locally.\n\n")
		fmt.Fprintf(os.Stderr, "Usage:\n")
		fmt.Fprintf(os.Stderr, "  wandb-core leet [<run-directory>]\n")
		fmt.Fprintf(os.Stderr, "  wandb-core leet --help\n\n")
		fmt.Fprintf(os.Stderr, "Arguments:\n")
		fmt.Fprintf(os.Stderr, "  <run-directory>       Path to a W&B run directory containing a .wandb file\n")
		fmt.Fprintf(os.Stderr, "                        Example: /path/to/.wandb/run-20250731_170606-iazb7i1k\n\n")
		fmt.Fprintf(os.Stderr, "                        If no directory is specified, 'leet' will look for\n")
		fmt.Fprintf(os.Stderr, "                        the latest-run symlink in ./wandb or ./.wandb\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		fmt.Fprintf(os.Stderr, "  -h, --help            Show this help message\n\n")
		fmt.Fprintf(os.Stderr, "Environment Variables:\n")
		fmt.Fprintf(os.Stderr, "  WANDB_DEBUG           Enable debug logging (creates wandb-leet.debug.log)\n")
		fmt.Fprintf(os.Stderr, "  WANDB_ERROR_REPORTING Enable/disable error reporting (default: true)\n")
	}

	if err := fs.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	if helpFlag {
		fs.Usage()
		return 0
	}

	// Sentry reporting controlled by WANDB_ERROR_REPORTING.
	enableErrorReporting := true
	if v := os.Getenv("WANDB_ERROR_REPORTING"); v != "" {
		enableErrorReporting, _ = strconv.ParseBool(v)
	}
	sentryClient := sentry_ext.New(sentry_ext.Params{
		DSN:              "https://2fbeaa43dbe0ed35e536adc7f019ba17@o151352.ingest.us.sentry.io/4507273364242432",
		Disabled:         !enableErrorReporting,
		AttachStacktrace: true,
		Release:          version.Version,
		Environment:      version.Environment,
	})
	sentryClient.CaptureMessage("wandb-leet", nil)
	defer sentryClient.Flush(2)

	// Debug logging controlled by WANDB_DEBUG.
	writer := io.Discard
	if os.Getenv("WANDB_DEBUG") != "" {
		loggerFile, err := os.OpenFile("wandb-leet.debug.log", os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			fmt.Println("fatal:", err)
			return 1
		}
		writer = loggerFile
		defer func() { _ = loggerFile.Close() }()
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{Level: slog.LevelDebug},
		)),
		&observability.CoreLoggerParams{
			Tags:   observability.Tags{},
			Sentry: sentryClient,
		},
	)

	// Determine the run directory.
	var runDir string
	switch fs.NArg() {
	case 0:
		dir, err := findLatestRun()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			fmt.Fprintf(os.Stderr, "\nTry specifying a run directory explicitly:\n")
			fmt.Fprintf(os.Stderr, "  wandb-core leet <run-directory>\n")
			return 1
		}
		runDir = dir
	case 1:
		providedPath := fs.Arg(0)
		if info, err := os.Lstat(providedPath); err == nil && info.Mode()&os.ModeSymlink != 0 {
			resolved, err := filepath.EvalSymlinks(providedPath)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: cannot resolve symlink %s: %v\n", providedPath, err)
				return 1
			}
			runDir = resolved
		} else {
			runDir = providedPath
		}
		absRunDir, err := filepath.Abs(runDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: cannot get absolute path for %s: %v\n", runDir, err)
			return 1
		}
		runDir = absRunDir
	default:
		fmt.Fprintf(os.Stderr, "Error: too many arguments\n\n")
		fs.Usage()
		return 1
	}

	wandbFile, err := findWandbFile(runDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	model := leet.NewModel(wandbFile, logger)
	p := tea.NewProgram(model, tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		logger.CaptureError(fmt.Errorf("wandb-leet: %v", err))
		return 1
	}
	return 0
}

// findLatestRun looks for the latest-run symlink in wandb or .wandb directories.
func findLatestRun() (string, error) {
	wandbDirs := []string{"wandb", ".wandb"}
	for _, dir := range wandbDirs {
		if _, err := os.Stat(dir); err != nil {
			continue
		}
		latestRunPath := filepath.Join(dir, "latest-run")
		info, err := os.Lstat(latestRunPath)
		if err != nil || info.Mode()&os.ModeSymlink == 0 {
			continue
		}
		target, err := filepath.EvalSymlinks(latestRunPath)
		if err != nil {
			return "", fmt.Errorf("cannot resolve latest-run symlink in %s: %w", dir, err)
		}
		absTarget, err := filepath.Abs(target)
		if err != nil {
			return "", fmt.Errorf("cannot get absolute path for %s: %w", target, err)
		}
		targetInfo, err := os.Stat(absTarget)
		if err != nil {
			return "", fmt.Errorf("latest-run symlink target does not exist: %w", err)
		}
		if !targetInfo.IsDir() {
			return "", fmt.Errorf("latest-run symlink does not point to a directory")
		}
		return absTarget, nil
	}
	return "", fmt.Errorf("no latest-run symlink found in ./wandb or ./.wandb")
}

// findWandbFile searches for a .wandb file in the given directory.
func findWandbFile(dir string) (string, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return "", fmt.Errorf("cannot access directory: %w", err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("path is not a directory: %s", dir)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "", fmt.Errorf("cannot read directory: %w", err)
	}
	var wandbFiles []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".wandb") {
			wandbFiles = append(wandbFiles, e.Name())
		}
	}
	if len(wandbFiles) == 0 {
		return "", fmt.Errorf("no .wandb file found in directory: %s", dir)
	}
	if len(wandbFiles) > 1 {
		return "", fmt.Errorf("multiple .wandb files found in directory: %s", dir)
	}
	return filepath.Join(dir, wandbFiles[0]), nil
}
