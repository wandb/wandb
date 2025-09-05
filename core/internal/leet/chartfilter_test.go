package leet_test

import (
	"os"
	"strings"
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

	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(120, 40))

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
