package leet_test

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

// This test exercises the chart filter via the public Bubble Tea model:
// 1) seed charts (train/loss, accuracy, val/accuracy),
// 2) apply filter "loss" using `/` + "loss" + Enter,
// 3) verify only *loss* charts show,
// 4) clear the filter with Ctrl+L and verify all charts reappear.
func TestChartFilter_FilterAndClear(t *testing.T) {
	t.Parallel()

	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)

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
	if !strings.Contains(out, "train/loss") || !strings.Contains(out, "accuracy") {
		t.Fatalf("expected initial charts in view; got:\n%s", out)
	}

	// Enter chart-filter mode and type "loss".
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("loss")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	out = m.View()
	if !strings.Contains(out, "train/loss") {
		t.Fatalf("expected 'train/loss' to be visible after filter 'loss'; got:\n%s", out)
	}
	if strings.Contains(out, "accuracy") || strings.Contains(out, "val/accuracy") {
		t.Fatalf("expected accuracy charts to be hidden after filter 'loss'; got:\n%s", out)
	}

	// Clear the filter (Ctrl+L).
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyCtrlL})

	out = m.View()
	if !strings.Contains(out, "train/loss") || !strings.Contains(out, "accuracy") || !strings.Contains(out, "val/accuracy") {
		t.Fatalf("expected all charts after clearing filter; got:\n%s", out)
	}
}

// Once a filter is active, new matching charts should appear automatically.
// Here we filter by "loss", then publish a new metric "val/loss" and a non-matching one.
// Expect: "val/loss" shows; "val/accuracy" remains hidden.
func TestChartFilter_NewChartsRespectActiveFilter(t *testing.T) {
	t.Parallel()

	// Create a real file so model init doesn't fail.
	tmp, err := os.CreateTemp(t.TempDir(), "empty-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	_ = tmp.Close()

	logger := observability.NewNoOpLogger()
	m := leet.NewModel(tmp.Name(), logger)

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
	t.Parallel()

	// Create a real file so model init doesn't fail.
	tmp, err := os.CreateTemp(t.TempDir(), "empty-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	_ = tmp.Close()

	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel(tmp.Name(), logger)

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
	if !strings.Contains(view, "train/loss") || !strings.Contains(view, "val/loss") {
		t.Fatal("Expected loss charts to be visible")
	}
	if strings.Contains(view, "train/accuracy") {
		t.Fatal("Expected accuracy chart to be hidden")
	}

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
	if !strings.Contains(view, "test/loss") {
		t.Fatal("New matching chart 'test/loss' should be visible")
	}

	// Non-matching chart should remain hidden
	if strings.Contains(view, "test/accuracy") || strings.Contains(view, "train/accuracy") {
		t.Fatal("Accuracy charts should remain hidden")
	}

	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'q'}})
}

// Switching filters should update the grid immediately.
// Filter "acc" should show both "accuracy" and "val/accuracy" and hide "train/loss".
func TestChartFilter_SwitchFilter(t *testing.T) {
	t.Parallel()

	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)

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
	if strings.Contains(out, "train/loss") {
		t.Fatalf("did not expect 'train/loss' under filter 'acc'; got:\n%s", out)
	}
	if !strings.Contains(out, "accuracy") || !strings.Contains(out, "val/accuracy") {
		t.Fatalf("expected accuracy charts under filter 'acc'; got:\n%s", out)
	}
}

// TestConcurrentFilterAndUpdate tests that filtering and chart updates don't deadlock
func TestConcurrentFilterAndUpdate(t *testing.T) {
	t.Parallel()

	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)

	// Set up initial state
	m, _ = m.Update(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Seed some initial metrics
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{
			"train/loss": 0.5,
			"accuracy":   0.8,
		},
	})

	// Use WaitGroup to synchronize goroutines
	var wg sync.WaitGroup
	errors := make(chan error, 10)
	done := make(chan bool)

	// Start multiple goroutines that simulate concurrent operations
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
			m, _ = m.Update(msg)
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
			m, _ = m.Update(msg)
			time.Sleep(time.Millisecond)
		}
	}()

	// Goroutine 3: Apply filters
	go func() {
		defer wg.Done()
		filters := []string{"loss", "acc", "metric", "*_1*", ""}
		for i := range 20 {
			filter := filters[i%len(filters)]

			// Start filter mode
			m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})

			// Type filter
			for _, r := range filter {
				m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
			}

			// Apply filter
			m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

			time.Sleep(5 * time.Millisecond)
		}
	}()

	// Goroutine 4: Clear filters
	go func() {
		defer wg.Done()
		for range 10 {
			m, _ = m.Update(tea.KeyMsg{Type: tea.KeyCtrlL})
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
	case err := <-errors:
		t.Fatalf("Error during concurrent operations: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatal("Test timed out - possible deadlock")
	}

	// Verify model is still in valid state
	view := m.View()
	if len(view) == 0 {
		t.Fatal("Model view is empty after concurrent operations")
	}
}

// TestFilterEdgeCases tests edge cases in filter functionality
func TestFilterEdgeCases(t *testing.T) {
	t.Parallel()

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
			var m tea.Model = leet.NewModel("dummy", logger)

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
				if !strings.Contains(view, chart) {
					t.Errorf("Expected chart '%s' to be visible", chart)
				}
			}

			// Check expected hidden charts
			for _, chart := range tt.expectHidden {
				if strings.Contains(view, chart) {
					t.Errorf("Expected chart '%s' to be hidden", chart)
				}
			}
		})
	}
}
