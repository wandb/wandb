package leet_test

import (
	"bytes"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestTUI_LoadingHelpAndQuit_Teatest(t *testing.T) {
	t.Parallel()

	logger := observability.NewNoOpLogger()
	m := leet.NewModel("no/such/file.wandb", logger)

	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(100, 30))

	// Send a window size to trigger first render
	tm.Send(tea.WindowSizeMsg{Width: 100, Height: 30})

	// Load the tiny golden substring and wait until it appears
	want := []byte("Loading data...")

	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, want) },
		teatest.WithDuration(2*time.Second),
	)

	// Toggle help
	tm.Type("h")
	tm.Type("h")

	// Quit
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(2*time.Second))
}
