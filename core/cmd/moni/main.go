package main

import (
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strconv"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/tui"
	"github.com/wandb/wandb/core/internal/version"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	exitCode := mainWithExitCode()
	os.Exit(exitCode)
}

func mainWithExitCode() int {
	flag.Parse()

	if flag.NArg() != 1 {
		// TODO: make this nicer.
		fmt.Fprintf(os.Stderr, "Usage: %s <path-to-wandb-file>\n", os.Args[0])
		os.Exit(1)
	}

	// Sentry reporting.
	enableErrorReporting, _ := strconv.ParseBool(os.Getenv("WANDB_ERROR_REPORTING"))

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
		loggerFile, err := os.OpenFile("wandb_observer.debug.log", os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
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

	// TODO: make this nicer.
	runPath := flag.Arg(0)

	// Create the model
	model := tui.NewModel(runPath, logger)

	// Initialize the program
	p := tea.NewProgram(model, tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		logger.Error(fmt.Sprintf("observer: %v", err))
		return 1
	}

	return 0
}
