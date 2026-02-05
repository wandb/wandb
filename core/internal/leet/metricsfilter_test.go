package leet_test

import (
	"fmt"
	"strings"
	"sync"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

type ComponentWithContentFilter interface {
	UpdateFilterDraft(msg tea.KeyMsg)
}

func typeString(c ComponentWithContentFilter, s string) {
	for _, r := range s {
		c.UpdateFilterDraft(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
	}
}

func TestMetricsGridFilter_ApplyAndClear(t *testing.T) {
	w, h := 240, 80
	grid := newMetricsGrid(t, 2, 2, w, h, nil)

	d := map[string]leet.MetricData{
		"train/loss": {
			X: []float64{1},
			Y: []float64{0.9},
		},
		"accuracy": {
			X: []float64{1},
			Y: []float64{0.71},
		},
		"val/accuracy": {
			X: []float64{1},
			Y: []float64{0.69},
		},
	}
	m := leet.HistoryMsg{Metrics: d}
	grid.ProcessHistory(m)

	dims := grid.CalculateChartDimensions(w, h)

	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")

	grid.EnterFilterMode()
	typeString(grid, "loss")
	grid.ExitFilterMode(true)
	out = grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.NotContains(t, out, "accuracy")

	grid.ClearFilter()
	out = grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "val/accuracy")
}

func TestMetricsGridFilter_NewChartsRespectActiveFilter(t *testing.T) {
	w, h := 80, 60
	grid := newMetricsGrid(t, 2, 2, w, h, nil)

	d := map[string]leet.MetricData{
		"train/loss": {
			X: []float64{1},
			Y: []float64{1.0},
		},
		"accuracy": {
			X: []float64{1},
			Y: []float64{0.5},
		},
	}
	m := leet.HistoryMsg{Metrics: d}
	grid.ProcessHistory(m)
	dims := grid.CalculateChartDimensions(w, h)

	grid.EnterFilterMode()
	typeString(grid, "loss")
	grid.ExitFilterMode(true)

	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.NotContains(t, out, "accuracy")

	// New charts arrive after filter applied.
	d = map[string]leet.MetricData{
		"val/loss": {
			X: []float64{2},
			Y: []float64{0.8},
		},
		"val/accuracy": {
			X: []float64{0.8},
			Y: []float64{0.6},
		},
	}
	m = leet.HistoryMsg{Metrics: d}
	grid.ProcessHistory(m)

	out = grid.View(dims)
	require.Contains(t, out, "val/loss")
	require.NotContains(t, out, "val/accuracy")
}

func TestMetricsGridFilter_SwitchFilter(t *testing.T) {
	w, h := 240, 80
	grid := newMetricsGrid(t, 2, 2, w, h, nil)
	d := map[string]leet.MetricData{
		"train/loss": {
			X: []float64{1},
			Y: []float64{0.9},
		},
		"accuracy": {
			X: []float64{1},
			Y: []float64{0.7},
		},
		"val/accuracy": {
			X: []float64{1},
			Y: []float64{0.65},
		},
	}
	m := leet.HistoryMsg{Metrics: d}
	grid.ProcessHistory(m)
	dims := grid.CalculateChartDimensions(w, h)

	grid.EnterFilterMode()
	typeString(grid, "loss")
	grid.ExitFilterMode(true)
	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.NotContains(t, out, "accuracy")

	// Switch to "acc".
	grid.ClearFilter()
	grid.EnterFilterMode()
	typeString(grid, "acc")
	grid.ExitFilterMode(true)
	out = grid.View(dims)
	require.NotContains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")
	require.Contains(t, out, "val/accuracy")
}

func TestMetricsGridFilter_EdgeCases(t *testing.T) {
	type tc struct {
		name          string
		metrics       map[string]leet.MetricData
		filter        string
		expectVisible []string
		expectHidden  []string
	}

	tests := []tc{
		{
			name: "empty_filter_shows_all",
			metrics: map[string]leet.MetricData{
				"a": {X: []float64{0}, Y: []float64{1}},
				"b": {X: []float64{0}, Y: []float64{2}},
				"c": {X: []float64{0}, Y: []float64{3}},
			},
			filter:        "",
			expectVisible: []string{"a", "b", "c"},
		},
		{
			name: "wildcard_star_shows_all",
			metrics: map[string]leet.MetricData{
				"train/loss": {X: []float64{0}, Y: []float64{1}},
				"val/loss":   {X: []float64{0}, Y: []float64{2}},
				"accuracy":   {X: []float64{0}, Y: []float64{3}},
			},
			filter:        "*",
			expectVisible: []string{"train/loss", "val/loss", "accuracy"},
		},
		{
			name: "glob_pattern_with_star",
			metrics: map[string]leet.MetricData{
				"train/loss": {X: []float64{0}, Y: []float64{1}},
				"train/acc":  {X: []float64{0}, Y: []float64{2}},
				"val/loss":   {X: []float64{0}, Y: []float64{3}},
				"test":       {X: []float64{0}, Y: []float64{4}},
			},
			filter:        "train/*",
			expectVisible: []string{"train/loss", "train/acc"},
			expectHidden:  []string{"val/loss", "test"},
		},
		{
			name: "case_insensitive_match",
			metrics: map[string]leet.MetricData{
				"Train/Loss": {X: []float64{0}, Y: []float64{1}},
				"TRAIN/ACC":  {X: []float64{0}, Y: []float64{2}},
				"val/LOSS":   {X: []float64{0}, Y: []float64{3}},
			},
			filter:        "train",
			expectVisible: []string{"Train/Loss", "TRAIN/ACC"},
			expectHidden:  []string{"val/LOSS"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w, h := 240, 80
			grid := newMetricsGrid(t, 2, 2, w, h, nil)
			m := leet.HistoryMsg{Metrics: tt.metrics}
			grid.ProcessHistory(m)
			dims := grid.CalculateChartDimensions(w, h)

			// Switch to glob match mode (defaults to regex).
			grid.ToggleFilterMatchMode()
			grid.EnterFilterMode()
			typeString(grid, tt.filter)
			grid.ExitFilterMode(true)
			view := grid.View(dims)

			for _, chart := range tt.expectVisible {
				require.Contains(t, view, chart, "chart should be visible")
			}
			for _, chart := range tt.expectHidden {
				require.NotContains(t, view, chart, "chart should be hidden")
			}
		})
	}
}

func TestMetricsGridFilter_PreviewAndCancelAndApply(t *testing.T) {
	w, h := 240, 80
	grid := newMetricsGrid(t, 2, 2, w, h, nil)
	m := leet.HistoryMsg{Metrics: map[string]leet.MetricData{
		"loss":        {X: []float64{0}, Y: []float64{1}},
		"acc":         {X: []float64{0}, Y: []float64{2}},
		"val/acc":     {X: []float64{0}, Y: []float64{3}},
		"unrelated/x": {X: []float64{0}, Y: []float64{4}},
	}}
	grid.ProcessHistory(m)
	dims := grid.CalculateChartDimensions(w, h)

	// Start typing "lo", then cancel (Esc behavior).
	grid.EnterFilterMode()
	grid.UpdateFilterDraft(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'l'}})
	grid.UpdateFilterDraft(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'o'}})
	require.GreaterOrEqual(t, grid.FilteredChartCount(), 1)
	grid.ExitFilterMode(false) // cancel

	view := grid.View(dims)
	require.Contains(t, view, "loss")
	require.Contains(t, view, "acc")
	require.Contains(t, view, "val/acc")

	// Start another filter "acc", add data while typing, then apply.
	grid.EnterFilterMode()
	grid.UpdateFilterDraft(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'a'}})
	grid.UpdateFilterDraft(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'c'}})
	grid.UpdateFilterDraft(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'c'}})
	m = leet.HistoryMsg{Metrics: map[string]leet.MetricData{
		"val/loss": {X: []float64{1}, Y: []float64{5}},
	}}
	grid.ProcessHistory(m)
	grid.ExitFilterMode(true)

	view = grid.View(dims)
	require.Contains(t, view, "acc")
	require.Contains(t, view, "val/acc")
	require.NotContains(t, view, "loss")     // filtered out
	require.NotContains(t, view, "val/loss") // filtered out
}

func TestMetricsGridFilter_ConcurrentApplyAndUpdate_NoDeadlock(t *testing.T) {
	w, h := 140, 60
	grid := newMetricsGrid(t, 2, 2, w, h, nil)
	m := leet.HistoryMsg{Metrics: map[string]leet.MetricData{
		"train/loss": {X: []float64{1}, Y: []float64{0.5}},
		"accuracy":   {X: []float64{1}, Y: []float64{0.8}},
	}}
	grid.ProcessHistory(m)
	var wg sync.WaitGroup

	wg.Go(func() {
		for i := range 50 {
			m = leet.HistoryMsg{Metrics: map[string]leet.MetricData{
				"metric_" + fmt.Sprint('a'+(i%3)): {
					X: []float64{float64(2 + i)},
					Y: []float64{float64(i) * 0.1},
				},
			}}
			grid.ProcessHistory(m)
		}
	})

	wg.Go(func() {
		patterns := []string{"loss", "acc", "*_1*", ""}
		for i := range 40 {
			grid.EnterFilterMode()
			typeString(grid, patterns[i%len(patterns)])
			grid.ExitFilterMode(true)
			grid.ApplyFilter()
		}
	})

	wg.Wait()

	out := grid.View(grid.CalculateChartDimensions(w, h))
	require.NotEmpty(t, out, "grid should render")
	require.True(t, strings.Contains(out, "Metrics"), "section header should render")
}

func TestMetricsGrid_RegexFilter(t *testing.T) {
	w, h := 240, 80
	grid := newMetricsGrid(t, 2, 2, w, h, nil)

	d := map[string]leet.MetricData{
		"train/loss": {X: []float64{1}, Y: []float64{0.5}},
		"val/loss":   {X: []float64{1}, Y: []float64{0.6}},
		"train/acc":  {X: []float64{1}, Y: []float64{0.9}},
	}
	m := leet.HistoryMsg{Metrics: d}
	grid.ProcessHistory(m)
	dims := grid.CalculateChartDimensions(w, h)

	// Default mode is regex. Filter for "ends with loss".
	grid.EnterFilterMode()
	typeString(grid, "loss$")
	grid.ExitFilterMode(true)

	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "val/loss")
	require.NotContains(t, out, "train/acc")

	// Toggle to glob mode.
	grid.ClearFilter()
	grid.EnterFilterMode()
	grid.ToggleFilterMatchMode()
	typeString(grid, "loss$")
	grid.ExitFilterMode(true)
	out = grid.View(dims)
	require.NotContains(t, out, "train/loss") // Glob shouldn't match regex syntax.

	// Test glob syntax.
	grid.ClearFilter()
	grid.EnterFilterMode()
	typeString(grid, "train/*")
	grid.ExitFilterMode(true)
	out = grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "train/acc")
	require.NotContains(t, out, "val/loss")
}
