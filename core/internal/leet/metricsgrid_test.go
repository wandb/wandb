package leet_test

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	leet "github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func newMetricsGrid(t *testing.T, rows, cols, width, height int, focus *leet.Focus) *leet.MetricsGrid {
	t.Helper()
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	require.NoError(t, cfg.SetMetricsRows(rows))
	require.NoError(t, cfg.SetMetricsCols(cols))

	if focus == nil {
		focus = &leet.Focus{}
	}

	grid := leet.NewMetricsGrid(cfg, focus, logger)
	grid.UpdateDimensions(width, height)
	return grid
}

func TestCalculateChartDimensions_RespectsMinimums(t *testing.T) {
	grid := newMetricsGrid(t, 2, 2, 200, 80, nil)

	d := grid.CalculateChartDimensions(10, 5) // small on purpose
	require.GreaterOrEqual(t, d.CellW, leet.MinChartWidth)
	require.GreaterOrEqual(t, d.CellH, leet.MinChartHeight)
}

func TestMetricsGrid_Render_EmptyGridShowsSectionHeader(t *testing.T) {
	grid := newMetricsGrid(t, 2, 2, 200, 80, nil)

	dims := grid.CalculateChartDimensions(200, 80)

	out := grid.View(dims)
	require.Contains(t, out, "Metrics", "section header should always be present")
}

func TestMetricsGrid_Lifecycle(t *testing.T) {
	// 1 row x 2 cols so 3 charts produce 2 pages.
	w, h := 200, 20
	grid := newMetricsGrid(t, 1, 2, w, h, nil)

	d := map[string]leet.MetricData{
		"zeta": {
			X: []float64{1},
			Y: []float64{1.0},
		},
		"alpha": {
			X: []float64{1},
			Y: []float64{2.0},
		},
		"beta": {
			X: []float64{1},
			Y: []float64{3.0},
		},
	}
	created := grid.ProcessHistory(d)
	require.True(t, created, "ingestion should report that there is something to draw")
	grid.UpdateDimensions(w, h)

	dims := grid.CalculateChartDimensions(w, h)
	out := grid.View(dims)

	a := strings.Index(out, "alpha")
	b := strings.Index(out, "beta")
	z := strings.Index(out, "zeta")
	require.Greater(t, a, 0, "alpha should be present in view")
	require.Greater(t, b, 0, "beta should be present in view")
	require.Equal(t, z, -1, "zeta should not be present in view")
	require.Less(t, a, b, "expected alpha before beta as chart should be sorted alphabetically")
	require.Contains(t, out, " [1-2 of 3]", "expected nav info for 2-wide page over 3 total charts")

	grid.Navigate(1)
	out = grid.View(dims)
	a = strings.Index(out, "alpha")
	b = strings.Index(out, "beta")
	z = strings.Index(out, "zeta")
	require.Equal(t, a, -1, "alpha should not be present in view")
	require.Equal(t, b, -1, "beta should not be present in view")
	require.Greater(t, z, 0, "zeta should be present in view")
	require.Contains(t, out, " [3-3 of 3]", "expected nav info for 1-wide page over 3 total charts")
}

func TestMetricsGrid_Navigate_ClearsMainChartFocus(t *testing.T) {
	f := &leet.Focus{}
	w, h := 120, 20
	// 1 row x 1 cols so 2 charts produce 2 pages.
	grid := newMetricsGrid(t, 1, 1, w, h, f)
	d := map[string]leet.MetricData{
		"alpha": {
			X: []float64{1},
			Y: []float64{1},
		},
		"beta": {
			X: []float64{1},
			Y: []float64{2},
		},
	}
	grid.ProcessHistory(d)
	grid.UpdateDimensions(w, h)

	// Focus on the first metric chart.
	f.Type = leet.FocusMainChart
	f.Row, f.Col = 0, 0
	f.Title = "alpha"

	grid.Navigate(1)
	require.Equal(t, leet.FocusNone, f.Type, "focus should be cleared after navigation")
}

func TestMetricsGrid_PreservesFocusAcrossHistoryUpdates(t *testing.T) {
	f := &leet.Focus{}
	w, h := 120, 20
	grid := newMetricsGrid(t, 2, 2, w, h, f)
	d := map[string]leet.MetricData{
		"alpha": {
			X: []float64{1},
			Y: []float64{1},
		},
		"beta": {
			X: []float64{1},
			Y: []float64{2},
		},
	}
	grid.ProcessHistory(d)
	grid.UpdateDimensions(w, h)

	// Focus on the first metric chart.
	f.Type = leet.FocusMainChart
	f.Row, f.Col = 0, 0
	f.Title = "alpha"

	d = map[string]leet.MetricData{
		"gamma": {
			X: []float64{2},
			Y: []float64{3},
		},
	}
	grid.ProcessHistory(d)
	require.Equal(t, "alpha", f.Title, "expected focus restored to previous title")
}
