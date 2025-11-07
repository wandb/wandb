package leet_test

import (
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestMetricsGridFilter_ApplyAndClear(t *testing.T) {
	w, h := 240, 80
	grid := newMetricsGrid(t, 2, 2, w, h, nil)

	grid.ProcessHistory(1, map[string]float64{
		"train/loss":   0.9,
		"accuracy":     0.71,
		"val/accuracy": 0.69,
	})
	dims := grid.CalculateChartDimensions(w, h)

	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")

	grid.ApplyFilter("loss")
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

	grid.ProcessHistory(1, map[string]float64{
		"train/loss": 1.0,
		"accuracy":   0.5,
	})
	dims := grid.CalculateChartDimensions(w, h)

	grid.ApplyFilter("loss")
	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.NotContains(t, out, "accuracy")

	// New charts arrive after filter applied.
	grid.ProcessHistory(2, map[string]float64{
		"val/loss":     0.8,
		"val/accuracy": 0.6,
	})

	out = grid.View(dims)
	require.Contains(t, out, "val/loss")
	require.NotContains(t, out, "val/accuracy")
}

func TestMetricsGridFilter_SwitchFilter(t *testing.T) {
	w, h := 240, 80
	grid := newMetricsGrid(t, 2, 2, w, h, nil)
	grid.ProcessHistory(1, map[string]float64{
		"train/loss":   0.9,
		"accuracy":     0.7,
		"val/accuracy": 0.65,
	})
	dims := grid.CalculateChartDimensions(w, h)

	grid.ApplyFilter("loss")
	out := grid.View(dims)
	require.Contains(t, out, "train/loss")
	require.NotContains(t, out, "accuracy")

	// Switch to "acc".
	grid.ApplyFilter("acc")
	out = grid.View(dims)
	require.NotContains(t, out, "train/loss")
	require.Contains(t, out, "accuracy")
	require.Contains(t, out, "val/accuracy")
}

func TestMetricsGridFilter_EdgeCases(t *testing.T) {
	type tc struct {
		name          string
		metrics       map[string]float64
		filter        string
		expectVisible []string
		expectHidden  []string
	}

	tests := []tc{
		{
			name: "empty_filter_shows_all",
			metrics: map[string]float64{
				"a": 1, "b": 2, "c": 3,
			},
			filter:        "",
			expectVisible: []string{"a", "b", "c"},
		},
		{
			name: "wildcard_star_shows_all",
			metrics: map[string]float64{
				"train/loss": 1, "val/loss": 2, "accuracy": 3,
			},
			filter:        "*",
			expectVisible: []string{"train/loss", "val/loss", "accuracy"},
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
			w, h := 240, 80
			grid := newMetricsGrid(t, 2, 2, w, h, nil)
			grid.ProcessHistory(1, tt.metrics)
			dims := grid.CalculateChartDimensions(w, h)

			grid.ApplyFilter(tt.filter)
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
	grid.ProcessHistory(1, map[string]float64{
		"loss":        1.0,
		"acc":         0.5,
		"val/acc":     0.6,
		"unrelated/x": 1.1,
	})
	dims := grid.CalculateChartDimensions(w, h)

	// Start typing "lo", then cancel (Esc behavior).
	grid.EnterFilterMode()
	grid.SetFilterDraft("lo")
	require.GreaterOrEqual(t, grid.FilteredChartCount(), 1)
	grid.ExitFilterMode(false) // cancel

	view := grid.View(dims)
	require.Contains(t, view, "loss")
	require.Contains(t, view, "acc")
	require.Contains(t, view, "val/acc")

	// Start another filter "acc", add data while typing, then apply.
	grid.EnterFilterMode()
	grid.SetFilterDraft("acc")
	grid.ProcessHistory(2, map[string]float64{
		"val/loss": 1.1,
	})
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

	grid.ProcessHistory(1, map[string]float64{"train/loss": 0.5, "accuracy": 0.8})

	var wg sync.WaitGroup

	wg.Go(func() {
		for i := range 50 {
			grid.ProcessHistory(2+i, map[string]float64{
				"metric_" + fmt.Sprint('a'+(i%3)): float64(i) * 0.1,
			})
		}
	})

	wg.Go(func() {
		patterns := []string{"loss", "acc", "*_1*", ""}
		for i := range 40 {
			grid.ApplyFilter(patterns[i%len(patterns)])
		}
	})

	wg.Wait()

	out := grid.View(grid.CalculateChartDimensions(w, h))
	require.NotEmpty(t, out, "grid should render")
	require.True(t, strings.Contains(out, "Metrics"), "section header should render")
}
