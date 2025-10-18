package leet_test

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

// This test exercises the chart filter via the public Bubble Tea model:
// 1) seed charts (train/loss, accuracy, val/accuracy),
// 2) apply filter "loss" using `/` + "loss" + Enter,
// 3) verify only *loss* charts show,
// 4) clear the filter with Ctrl+L and verify all charts reappear.
func TestChartFilter_FilterAndClear(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewModel("dummy", cfg, logger)

	// Establish terminal size so the grid is laid out.
	m, _ = m.Update(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Seed a few metrics; this should create corresponding charts.
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"train/loss":   0.9,
			"accuracy":     0.71,
			"val/accuracy": 0.69,
		},
	})

	out := m.View()
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")

	// Enter chart-filter mode and type "loss".
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("loss")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	out = m.View()
	require.Contains(t, out, "train/loss")
	require.NotContains(t, out, "accuracy")
	require.NotContains(t, out, "val/accuracy")

	// Clear the filter (Ctrl+L).
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyCtrlL})

	out = m.View()
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")
	require.Contains(t, out, "val/accuracy")
}

// Once a filter is active, new matching charts should appear automatically.
// Here we filter by "loss", then publish a new metric "val/loss" and a non-matching one.
// Expect: "val/loss" shows; "val/accuracy" remains hidden.
func TestChartFilter_NewChartsRespectActiveFilter(t *testing.T) {
	// Create a real file so model init doesn't fail.
	tmp, err := os.CreateTemp(t.TempDir(), "empty-*.wandb")
	require.NoError(t, err)
	_ = tmp.Close()

	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	m := leet.NewModel(tmp.Name(), cfg, logger)

	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(240, 80))

	// Size the terminal and seed initial charts.
	tm.Send(tea.WindowSizeMsg{Width: 240, Height: 80})
	tm.Send(leet.HistoryMsg{Metrics: map[string]float64{
		"train/loss": 1.0,
		"accuracy":   0.5,
	}})

	// Apply filter "loss".
	tm.Send(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	tm.Type("loss")
	tm.Send(tea.KeyMsg{Type: tea.KeyEnter})

	tm.Send(leet.HistoryMsg{Metrics: map[string]float64{
		"val/loss":     0.8,
		"val/accuracy": 0.6,
	}})

	// Wait until the output reflects the expected state.
	teatest.WaitFor(t, tm.Output(), func(b []byte) bool {
		out := string(b)
		return strings.Contains(out, "train/loss") &&
			strings.Contains(out, "val/loss") &&
			!strings.Contains(out, "val/accuracy")
	}, teatest.WithDuration(2*time.Second))

	// Cleanly terminate to keep test output tidy.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(2*time.Second))
}

// TestFilterLiveUpdates tests filtering behavior during live data updates.
func TestFilterLiveUpdates(t *testing.T) {
	// Create a real file so model init doesn't fail.
	tmp, err := os.CreateTemp(t.TempDir(), "empty-*.wandb")
	require.NoError(t, err)
	_ = tmp.Close()

	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewModel(tmp.Name(), cfg, logger)

	m, _ = m.Update(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Add initial metrics
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"train/loss":     1.0,
			"train/accuracy": 0.5,
			"val/loss":       1.2,
		},
	})

	// Apply filter for "loss"
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("loss")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Verify initial filter state
	view := m.View()
	require.Contains(t, view, "train/loss")
	require.Contains(t, view, "val/loss")
	require.NotContains(t, view, "train/accuracy")

	// Add new metrics while filter is active
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"test/loss":     0.9, // Should appear
			"test/accuracy": 0.7, // Should not appear
		},
	})

	// Update existing metrics
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"train/loss": 0.8, // Update existing
			"val/loss":   1.0, // Update existing
		},
	})

	view = m.View()

	// New matching chart should appear
	require.Contains(t, view, "test/loss")

	// Non-matching chart should remain hidden
	require.NotContains(t, view, "test/accuracy")
	require.NotContains(t, view, "train/accuracy")

	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'q'}})
}

// Switching filters should update the grid immediately.
// Filter "acc" should show both "accuracy" and "val/accuracy" and hide "train/loss".
func TestChartFilter_SwitchFilter(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewModel("dummy", cfg, logger)

	m, _ = m.Update(tea.WindowSizeMsg{Width: 240, Height: 80})

	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"train/loss":   0.9,
			"accuracy":     0.7,
			"val/accuracy": 0.65,
		},
	})

	// Apply "acc".
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("acc")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	out := m.View()
	require.NotContains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")
	require.Contains(t, out, "val/accuracy")
}

// TestConcurrentFilterAndUpdate tests that filtering and chart updates don't deadlock
func TestConcurrentFilterAndUpdate(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	model := leet.NewModel("dummy", cfg, logger)

	// Set up initial state
	model.Update(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Seed some initial metrics
	model.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"train/loss": 0.5,
			"accuracy":   0.8,
		},
	})

	// Use WaitGroup to synchronize goroutines
	var wg sync.WaitGroup
	done := make(chan bool)

	// Use a mutex to serialize all Update calls
	var updateMu sync.Mutex

	// Start multiple goroutines that update the model
	wg.Add(4)

	// Goroutine 1: Continuously add new metrics
	go func() {
		defer wg.Done()
		for i := range 50 {
			metricName := fmt.Sprintf("metric_%d", i)
			msg := leet.HistoryMsg{
				Metrics: map[string]float64{
					metricName: float64(i) * 0.1,
				},
			}
			updateMu.Lock()
			model.Update(msg)
			updateMu.Unlock()
			time.Sleep(time.Millisecond)
		}
	}()

	// Goroutine 2: Update existing metrics
	go func() {
		defer wg.Done()
		for i := range 100 {
			msg := leet.HistoryMsg{
				Metrics: map[string]float64{
					"train/loss": 0.5 - float64(i)*0.001,
					"accuracy":   0.8 + float64(i)*0.001,
				},
			}
			updateMu.Lock()
			model.Update(msg)
			updateMu.Unlock()
			time.Sleep(time.Millisecond)
		}
	}()

	// Goroutine 3: Apply filters
	go func() {
		defer wg.Done()
		filters := []string{"loss", "acc", "metric", "*_1*", ""}
		for i := range 20 {
			filter := filters[i%len(filters)]

			updateMu.Lock()
			// Start filter mode
			model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
			// Type filter
			for _, r := range filter {
				model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
			}
			// Apply filter
			model.Update(tea.KeyMsg{Type: tea.KeyEnter})
			updateMu.Unlock()

			time.Sleep(5 * time.Millisecond)
		}
	}()

	// Goroutine 4: Clear filters
	go func() {
		defer wg.Done()
		for range 10 {
			updateMu.Lock()
			model.Update(tea.KeyMsg{Type: tea.KeyCtrlL})
			updateMu.Unlock()
			time.Sleep(10 * time.Millisecond)
		}
	}()

	// Wait for completion with timeout
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		// Success - no deadlock
	case <-time.After(5 * time.Second):
		t.Fatal("Test timed out - possible deadlock")
	}

	// Verify model is still in valid state
	view := model.View()
	require.NotEmpty(t, view)
}

// TestFilterEdgeCases tests edge cases in filter functionality
func TestFilterEdgeCases(t *testing.T) {
	tests := []struct {
		name          string
		metrics       map[string]float64
		filter        string
		expectVisible []string
		expectHidden  []string
	}{
		{
			name: "empty_filter_shows_all",
			metrics: map[string]float64{
				"a": 1, "b": 2, "c": 3,
			},
			filter:        "",
			expectVisible: []string{"a", "b", "c"},
			expectHidden:  []string{},
		},
		{
			name: "wildcard_star_shows_all",
			metrics: map[string]float64{
				"train/loss": 1, "val/loss": 2, "accuracy": 3,
			},
			filter:        "*",
			expectVisible: []string{"train/loss", "val/loss", "accuracy"},
			expectHidden:  []string{},
		},
		{
			name: "glob_pattern_with_star",
			metrics: map[string]float64{
				"train/loss": 1, "train/acc": 2, "val/loss": 3, "test": 4,
			},
			filter:        "train/*",
			expectVisible: []string{"train/loss", "train/acc"},
			expectHidden:  []string{"val/loss", "test"},
		},
		{
			name: "case_insensitive_match",
			metrics: map[string]float64{
				"Train/Loss": 1, "TRAIN/ACC": 2, "val/LOSS": 3,
			},
			filter:        "train",
			expectVisible: []string{"Train/Loss", "TRAIN/ACC"},
			expectHidden:  []string{"val/LOSS"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			logger := observability.NewNoOpLogger()
			cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
			var m tea.Model = leet.NewModel("dummy", cfg, logger)

			m, _ = m.Update(tea.WindowSizeMsg{Width: 240, Height: 80})
			m, _ = m.Update(leet.HistoryMsg{Metrics: tt.metrics})

			// Apply filter
			if tt.filter != "" {
				m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
				for _, r := range tt.filter {
					m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
				}
				m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})
			}

			view := m.View()

			// Check expected visible charts
			for _, chart := range tt.expectVisible {
				require.Contains(t, view, chart, "chart should be visible")
			}

			// Check expected hidden charts
			for _, chart := range tt.expectHidden {
				require.NotContains(t, view, chart, "chart should be hidden")
			}
		})
	}
}

// TestFilterModeInterruption tests interrupting filter mode with other operations
func TestFilterModeInterruption(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewModel("dummy", cfg, logger)

	m, _ = m.Update(tea.WindowSizeMsg{Width: 240, Height: 80})
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"loss": 1.0,
			"acc":  0.5,
		},
	})

	// Start typing a filter
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("lo")})

	// Interrupt with ESC
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEsc})

	// View should show all charts (filter not applied)
	view := m.View()
	require.Contains(t, view, "loss")
	require.Contains(t, view, "acc")

	// Start another filter
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("acc")})

	// Add new data while in filter mode
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"val/acc":  0.6,
			"val/loss": 1.1,
		},
	})

	// Complete the filter
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	view = m.View()
	// Should show only "acc" charts
	require.Contains(t, view, "acc")
	require.Contains(t, view, "val/acc")
	require.NotContains(t, view, "loss")
	require.NotContains(t, view, "val/loss")
}
