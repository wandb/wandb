package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/wandb/wandb/core/internal/tui"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	flag.Parse()

	if flag.NArg() != 1 {
		fmt.Fprintf(os.Stderr, "Usage: %s <path-to-wandb-file>\n", os.Args[0])
		os.Exit(1)
	}

	runPath := flag.Arg(0)

	// Create the model
	model := tui.NewModel(runPath)

	// Initialize the program
	p := tea.NewProgram(model, tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		fmt.Printf("Error: %v", err)
		os.Exit(1)
	}
}
