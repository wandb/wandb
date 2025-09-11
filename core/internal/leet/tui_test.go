package leet_test

import (
	"bytes"
	"os"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

// setupTestConfig creates an isolated config file for testing.
// This prevents race conditions when tests run in parallel.
func setupTestConfig(t *testing.T) *leet.ConfigManager {
	t.Helper()

	tmp, err := os.CreateTemp(t.TempDir(), "config-*.json")
	if err != nil {
		t.Fatalf("failed to create temp config file: %v", err)
	}
	// Write empty JSON object to the file
	if _, err := tmp.Write([]byte("{}")); err != nil {
		tmp.Close()
		t.Fatalf("failed to write config file: %v", err)
	}
	tmp.Close()

	cfg := leet.GetConfig()
	cfg.SetPathForTests(tmp.Name())
	if err := cfg.Load(); err != nil {
		t.Fatalf("failed to load config: %v", err)
	}

	return cfg
}

func TestTUI_LoadingHelpAndQuit_Teatest(t *testing.T) {
	_ = setupTestConfig(t)
	logger := observability.NewNoOpLogger()
	m := leet.NewModel("no/such/file.wandb", logger)

	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(100, 30))

	// Send a window size to trigger first render
	tm.Send(tea.WindowSizeMsg{Width: 100, Height: 30})

	// Wait for loading screen
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

func TestTUI_SystemMetrics_ToggleAndRender_Teatest(t *testing.T) {
	// Setup config with 2x2 system grid
	cfg := setupTestConfig(t)
	if err := cfg.SetSystemRows(2); err != nil {
		t.Fatalf("config SetSystemRows: %v", err)
	}
	if err := cfg.SetSystemCols(2); err != nil {
		t.Fatalf("config SetSystemCols: %v", err)
	}
	leet.UpdateGridDimensions()

	// Create model and test terminal
	logger := observability.NewNoOpLogger()
	m := leet.NewModel("no/such/file.wandb", logger)
	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(240, 80))

	// Set window size
	tm.Send(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Exit loading screen by providing some metric data
	tm.Send(leet.BatchedRecordsMsg{
		Msgs: []tea.Msg{
			leet.HistoryMsg{Metrics: map[string]float64{"loss": 1.0}, Step: 1},
		},
	})

	// Wait for the metrics grid to appear (loss chart should be visible)
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("loss")) },
		teatest.WithDuration(2*time.Second),
	)

	// Provide system stats
	ts := time.Now().Unix()
	tm.Send(leet.StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"gpu.1.temp":        42,
			"cpu.0.cpu_percent": 55,
		},
	})

	// Toggle right sidebar open
	tm.Send(tea.KeyMsg{Type: tea.KeyCtrlN})

	// Wait for System Metrics header
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("System Metrics")) },
		teatest.WithDuration(3*time.Second),
	)

	// Check for GPU Temp chart with 2 series (should show [2])
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			hasGPUTemp := bytes.Contains(b, []byte("GPU Temp"))
			hasSeriesCount := bytes.Contains(b, []byte("[2]"))
			hasCPUCore := bytes.Contains(b, []byte("CPU Core"))
			return hasGPUTemp && hasSeriesCount && hasCPUCore
		},
		teatest.WithDuration(3*time.Second),
	)

	// Add third GPU
	tm.Send(leet.StatsMsg{
		Timestamp: ts + 1,
		Metrics:   map[string]float64{"gpu.2.temp": 44},
	})

	// Wait for [3] to appear
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("[3]")) },
		teatest.WithDuration(3*time.Second),
	)

	// Quit
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(2*time.Second))
}
