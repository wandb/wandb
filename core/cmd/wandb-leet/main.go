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

func main() {
	exitCode := mainWithExitCode()
	os.Exit(exitCode)
}

func mainWithExitCode() int {
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "wandb-leet - Lightweight Experiment Exploration Tool\n\n")
		fmt.Fprintf(os.Stderr, "A terminal UI for viewing your W&B runs locally.\n\n")
		fmt.Fprintf(os.Stderr, "Usage:\n")
		fmt.Fprintf(os.Stderr, "  wandb-leet <run-directory>\n\n")
		fmt.Fprintf(os.Stderr, "Arguments:\n")
		fmt.Fprintf(os.Stderr, "  <run-directory>       Path to a W&B run directory containing a .wandb file\n")
		fmt.Fprintf(os.Stderr, "                        Example: /path/to/.wandb/run-20250731_170606-iazb7i1k\n\n")
		fmt.Fprintf(os.Stderr, "Environment Variables:\n")
		fmt.Fprintf(os.Stderr, "  WANDB_DEBUG           Enable debug logging (creates wandb-leet.debug.log)\n")
	}

	flag.Parse()

	if flag.NArg() != 1 {
		flag.Usage()
		os.Exit(1)
	}

	// Sentry reporting.
	enableErrorReporting := true
	if os.Getenv("WANDB_ERROR_REPORTING") != "" {
		enableErrorReporting, _ = strconv.ParseBool(os.Getenv("WANDB_ERROR_REPORTING"))
	}

	sentryClient := sentry_ext.New(sentry_ext.Params{
		Disabled:         !enableErrorReporting,
		AttachStacktrace: true,
		Release:          version.Version,
		Environment:      version.Environment,
	})
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

	// Get the directory path from arguments
	runDir := flag.Arg(0)

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
		logger.Error(fmt.Sprintf("observer: %v", err))
		return 1
	}

	return 0
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
