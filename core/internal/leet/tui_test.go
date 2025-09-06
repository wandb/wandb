package leet_test

import (
	"bytes"
	"path/filepath"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestTUI_LoadingHelpAndQuit_Teatest(t *testing.T) {
	tmpDir := t.TempDir()
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(tmpDir, "config.json"))
	_ = cfg.Load()

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

func TestTUI_SystemMetrics_ToggleAndRender_Teatest(t *testing.T) {
	// Not parallel: we mutate the singleton config path below.

	// --- Hermetic config (2x2 system grid) ---
	tmpDir := t.TempDir()
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(tmpDir, "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("config Load: %v", err)
	}
	if err := cfg.SetSystemRows(2); err != nil {
		t.Fatalf("config SetSystemRows: %v", err)
	}
	if err := cfg.SetSystemCols(2); err != nil {
		t.Fatalf("config SetSystemCols: %v", err)
	}

	// --- Model + test terminal ---
	logger := observability.NewNoOpLogger()
	m := leet.NewModel("no/such/file.wandb", logger)
	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(240, 80))

	// Set a size large enough for the right sidebar grid to meet min dimensions.
	tm.Send(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Exit loading screen by delivering a small batch with one history point.
	// (isLoading becomes false only when processing a batch with charts.)
	tm.Send(leet.BatchedRecordsMsg{
		Msgs: []tea.Msg{
			leet.HistoryMsg{Metrics: map[string]float64{"loss": 1.0}, Step: 1},
		},
	})

	// Provide synthetic system stats: two GPUs (same base key => one chart with 2 series)
	// + one CPU core.
	ts := time.Now().Unix()
	tm.Send(leet.StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"gpu.1.temp":        42,
			"cpu.0.cpu_percent": 55,
		},
	})

	// Toggle right sidebar open (system metrics).
	tm.Send(tea.KeyMsg{Type: tea.KeyCtrlN})

	// Wait for the right sidebar header to appear.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("System Metrics")) },
		teatest.WithDuration(3*time.Second),
	)

	// GPU Temp chart title should appear; with two GPU series "[2]" should be visible.
	// CPU Core chart title should also be present.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			return (bytes.Contains(b, []byte("GPU Temp")) &&
				bytes.Contains(b, []byte(" [2]")) &&
				bytes.Contains(b, []byte("CPU Core")))
		},
		teatest.WithDuration(3*time.Second),
	)

	// Add a third GPU series; the series count should update to [3].
	tm.Send(leet.StatsMsg{
		Timestamp: ts + 1,
		Metrics:   map[string]float64{"gpu.2.temp": 44},
	})
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte(" [3]")) },
		teatest.WithDuration(3*time.Second),
	)

	// Quit cleanly.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(2*time.Second))
}
