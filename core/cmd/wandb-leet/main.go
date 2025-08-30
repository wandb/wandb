package main

import (
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/version"

	tea "github.com/charmbracelet/bubbletea"
)

const sentryDSN = "https://2fbeaa43dbe0ed35e536adc7f019ba17@o151352.ingest.us.sentry.io/4507273364242432"

func main() {
	exitCode := mainWithExitCode()
	os.Exit(exitCode)
}

func mainWithExitCode() int {
	var helpFlag bool
	flag.BoolVar(&helpFlag, "help", false, "Show help message")
	flag.BoolVar(&helpFlag, "h", false, "Show help message (shorthand)")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "wandb-leet - Lightweight Experiment Exploration Tool\n\n")
		fmt.Fprintf(os.Stderr, "A terminal UI for viewing your W&B runs locally.\n\n")
		fmt.Fprintf(os.Stderr, "Usage:\n")
		fmt.Fprintf(os.Stderr, "  wandb-leet [<run-directory>]\n")
		fmt.Fprintf(os.Stderr, "  wandb-leet --help\n\n")
		fmt.Fprintf(os.Stderr, "Arguments:\n")
		fmt.Fprintf(os.Stderr, "  <run-directory>       Path to a W&B run directory containing a .wandb file\n")
		fmt.Fprintf(os.Stderr, "                        Example: /path/to/.wandb/run-20250731_170606-iazb7i1k\n\n")
		fmt.Fprintf(os.Stderr, "                        If no directory is specified, wandb-leet will look for\n")
		fmt.Fprintf(os.Stderr, "                        the latest-run symlink in ./wandb or ./.wandb\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		fmt.Fprintf(os.Stderr, "  -h, --help            Show this help message\n\n")
		fmt.Fprintf(os.Stderr, "Environment Variables:\n")
		fmt.Fprintf(os.Stderr, "  WANDB_DEBUG           Enable debug logging (creates wandb-leet.debug.log)\n")
		fmt.Fprintf(os.Stderr, "  WANDB_ERROR_REPORTING Enable/disable error reporting (default: true)\n")
	}

	flag.Parse()

	if helpFlag {
		flag.Usage()
		return 0
	}

	// Sentry reporting.
	enableErrorReporting := true
	if os.Getenv("WANDB_ERROR_REPORTING") != "" {
		enableErrorReporting, _ = strconv.ParseBool(os.Getenv("WANDB_ERROR_REPORTING"))
	}

	sentryClient := sentry_ext.New(sentry_ext.Params{
		DSN:              sentryDSN,
		Disabled:         !enableErrorReporting,
		AttachStacktrace: true,
		Release:          version.Version,
		Environment:      version.Environment,
	})
	// TODO: collect basic env info from experiment data.
	sentryClient.CaptureMessage("wandb-leet", nil)
	defer sentryClient.Flush(2)

	// Enable debug logging if WANDB_DEBUG env var is set.
	var writer io.Writer
	if os.Getenv("WANDB_DEBUG") != "" {
		loggerFile, err := os.OpenFile("wandb-leet.debug.log", os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			fmt.Println("fatal:", err)
			return 1
		}
		writer = loggerFile
		defer func() {
			_ = loggerFile.Close()
		}()
	} else {
		writer = io.Discard
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{
				Level: slog.LevelDebug,
			},
		)),
		&observability.CoreLoggerParams{
			Tags:   observability.Tags{},
			Sentry: sentryClient,
		},
	)

	// Determine the run directory
	var runDir string
	switch flag.NArg() {
	case 0:
		// No arguments provided, try to find latest-run
		dir, err := findLatestRun()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			fmt.Fprintf(os.Stderr, "\nTry specifying a run directory explicitly:\n")
			fmt.Fprintf(os.Stderr, "  wandb-leet <run-directory>\n")
			return 1
		}
		runDir = dir
	case 1:
		// Directory explicitly provided - resolve symlinks if necessary
		providedPath := flag.Arg(0)

		// Check if the provided path is a symlink and resolve it
		info, err := os.Lstat(providedPath)
		if err == nil && info.Mode()&os.ModeSymlink != 0 {
			// It's a symlink, resolve it
			resolved, err := filepath.EvalSymlinks(providedPath)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: cannot resolve symlink %s: %v\n", providedPath, err)
				return 1
			}
			runDir = resolved
		} else {
			runDir = providedPath
		}

		// Convert to absolute path for consistency
		absRunDir, err := filepath.Abs(runDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: cannot get absolute path for %s: %v\n", runDir, err)
			return 1
		}
		runDir = absRunDir
	default:
		// Too many arguments
		fmt.Fprintf(os.Stderr, "Error: too many arguments\n\n")
		flag.Usage()
		return 1
	}

	// Find the .wandb file in the directory
	wandbFile, err := findWandbFile(runDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	// Create the model
	model := leet.NewModel(wandbFile, logger)

	// Initialize the program
	p := tea.NewProgram(model, tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		logger.CaptureError(fmt.Errorf("wandb-leet: %v", err))
		return 1
	}

	return 0
}

// findLatestRun looks for the latest-run symlink in wandb or .wandb directories
func findLatestRun() (string, error) {
	// Try both "wandb" and ".wandb" directories
	wandbDirs := []string{"wandb", ".wandb"}

	for _, dir := range wandbDirs {
		if _, err := os.Stat(dir); err != nil {
			// Directory doesn't exist, try the next one
			continue
		}

		// Check for latest-run symlink
		latestRunPath := filepath.Join(dir, "latest-run")
		info, err := os.Lstat(latestRunPath)
		if err != nil {
			// latest-run doesn't exist in this directory
			continue
		}

		// Verify it's a symlink
		if info.Mode()&os.ModeSymlink == 0 {
			// Not a symlink, skip
			continue
		}

		// Resolve the symlink to get the actual path
		// This is critical for file watchers to work correctly
		target, err := filepath.EvalSymlinks(latestRunPath)
		if err != nil {
			return "", fmt.Errorf("cannot resolve latest-run symlink in %s: %w", dir, err)
		}

		// Convert to absolute path to ensure file watcher works correctly
		absTarget, err := filepath.Abs(target)
		if err != nil {
			return "", fmt.Errorf("cannot get absolute path for %s: %w", target, err)
		}

		// Verify the target exists and is a directory
		targetInfo, err := os.Stat(absTarget)
		if err != nil {
			return "", fmt.Errorf("latest-run symlink target does not exist: %w", err)
		}
		if !targetInfo.IsDir() {
			return "", fmt.Errorf("latest-run symlink does not point to a directory")
		}

		return absTarget, nil
	}

	// No latest-run found
	return "", fmt.Errorf("no latest-run symlink found in ./wandb or ./.wandb")
}

// findWandbFile searches for a .wandb file in the given directory
func findWandbFile(dir string) (string, error) {
	// Check if the directory exists
	info, err := os.Stat(dir)
	if err != nil {
		return "", fmt.Errorf("cannot access directory: %w", err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("path is not a directory: %s", dir)
	}

	// Read directory contents
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "", fmt.Errorf("cannot read directory: %w", err)
	}

	// Look for .wandb file
	var wandbFiles []string
	for _, entry := range entries {
		if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".wandb") {
			wandbFiles = append(wandbFiles, entry.Name())
		}
	}

	// Check results
	if len(wandbFiles) == 0 {
		return "", fmt.Errorf("no .wandb file found in directory: %s", dir)
	}
	if len(wandbFiles) > 1 {
		return "", fmt.Errorf("multiple .wandb files found in directory: %s", dir)
	}

	// Return the full path to the .wandb file
	return filepath.Join(dir, wandbFiles[0]), nil
}
