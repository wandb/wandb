package leet_test

import (
	"math"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	leet "github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func newMetricsGrid(
	t *testing.T,
	rows, cols, width, height int,
	focus *leet.Focus,
) *leet.MetricsGrid {
	t.Helper()
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	require.NoError(t, cfg.SetMetricsRows(rows))
	require.NoError(t, cfg.SetMetricsCols(cols))

	if focus == nil {
		focus = leet.NewFocus()
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

// computeAdjustedX builds a grid-absolute X such that relX within the chart equals wantRelX.
func computeAdjustedX(
	t *testing.T,
	chart *leet.EpochLineChart,
	cellWWithPad int,
	col, wantRelX int,
) int {
	t.Helper()
	chartStartX := col * cellWWithPad
	graphStartX := chartStartX + 1
	if chart.YStep() > 0 {
		graphStartX += chart.Origin().X + 1
	}
	return graphStartX + wantRelX
}

func TestMetricsGrid_Inspection_FocusedOnly(t *testing.T) {
	w, h := 240, 60
	grid := newMetricsGrid(t, 1, 2, w, h, nil)

	// Two charts: both share the same view initially.
	hist := map[string]leet.MetricData{
		"alpha": {X: []float64{0, 1, 2, 3, 4, 5}, Y: []float64{10, 20, 30, 40, 50, 60}},
		"beta":  {X: []float64{0, 1, 2, 3, 4, 5}, Y: []float64{100, 200, 300, 400, 500, 600}},
	}
	created := grid.ProcessHistory(hist)
	require.True(t, created)
	grid.UpdateDimensions(w, h)

	// Get dimensions + target chart to compute adjustedX.
	dims := grid.CalculateChartDimensions(w, h)
	ch0 := grid.TestChartAt(0, 0)
	require.NotNil(t, ch0)

	// Choose anchor X=3 -> rel pixel.
	relPX := int(math.Round(
		(3.0 - ch0.ViewMinX()) / (ch0.ViewMaxX() - ch0.ViewMinX()) *
			float64(ch0.GraphWidth()),
	))
	adjX := computeAdjustedX(t, ch0, dims.CellWWithPadding, 0, relPX)

	// Start non-synced inspection on (row=0,col=0).
	grid.StartInspection(adjX, 0, 0, dims, false /*synced*/)
	require.True(t, ch0.IsInspecting())
	require.False(t, grid.TestChartAt(0, 1).IsInspecting(), "other chart should not be inspecting")

	// Move to X=5; only the focused chart updates.
	relPX = int(math.Round(
		(5.0 - ch0.ViewMinX()) / (ch0.ViewMaxX() - ch0.ViewMinX()) *
			float64(ch0.GraphWidth()),
	))
	adjX = computeAdjustedX(t, ch0, dims.CellWWithPadding, 0, relPX)
	grid.UpdateInspection(adjX, 0, 0, dims)

	x0, _, active := ch0.InspectionData()
	require.True(t, active)
	require.InDelta(t, 5.0, x0, 1e-6)
	require.False(t, grid.TestChartAt(0, 1).IsInspecting())

	// End clears only the focused one.
	grid.EndInspection()
	require.False(t, ch0.IsInspecting())
}

func TestMetricsGrid_Inspection_Synchronized_BroadcastAndEnd(t *testing.T) {
	w, h := 240, 60
	grid := newMetricsGrid(t, 1, 2, w, h, nil)

	// alpha has dense steps, beta has sparse to exercise nearestIndex tie-breaks.
	hist := map[string]leet.MetricData{
		"alpha": {
			X: []float64{0, 1, 2, 3, 4, 5, 6, 7, 8, 9},
			Y: []float64{0, 1, 2, 3, 4, 5, 6, 7, 8, 9},
		},
		"beta": {
			X: []float64{0, 2, 4, 6, 8},
			Y: []float64{20, 40, 60, 80, 100},
		},
	}
	require.True(t, grid.ProcessHistory(hist))
	grid.UpdateDimensions(w, h)

	dims := grid.CalculateChartDimensions(w, h)

	chA := grid.TestChartAt(0, 0)
	chB := grid.TestChartAt(0, 1)
	require.NotNil(t, chA)
	require.NotNil(t, chB)

	// Start synchronized at X=3 on alpha.
	relPX := int(math.Round(
		(3.0 - chA.ViewMinX()) / (chA.ViewMaxX() - chA.ViewMinX()) *
			float64(chA.GraphWidth()),
	))
	adjX := computeAdjustedX(t, chA, dims.CellWWithPadding, 0, relPX)
	grid.StartInspection(adjX, 0, 0, dims /*synced*/, true)
	require.True(t, grid.TestSyncInspectActive())

	// Both charts should now be inspecting near the anchor X.
	xA, _, aActive := chA.InspectionData()
	xB, _, bActive := chB.InspectionData()
	require.True(t, aActive)
	require.True(t, bActive)
	require.InDelta(t, 3.0, xA, 1e-6) // alpha matches anchor exactly

	// For beta (X: {0,2,4,6,8}), nearest to 3 is a tie (2 and 4). Implementation picks the lower (2).
	require.InDelta(t, 2.0, xB, 1e-6)

	// Move synchronized anchor to ~X=7.
	relPX = int(math.Round(
		(7.0 - chA.ViewMinX()) / (chA.ViewMaxX() - chA.ViewMinX()) *
			float64(chA.GraphWidth()),
	))
	adjX = computeAdjustedX(t, chA, dims.CellWWithPadding, 0, relPX)
	grid.UpdateInspection(adjX, 0, 0, dims)

	xA, _, _ = chA.InspectionData()
	xB, _, _ = chB.InspectionData()
	require.InDelta(t, 7.0, xA, 1e-6)
	// For beta, nearest to 7 is 6 (tie 6/8 -> lower).
	require.InDelta(t, 6.0, xB, 1e-6)

	// End synchronized session should clear both.
	grid.EndInspection()
	require.False(t, grid.TestSyncInspectActive())
	require.False(t, chA.IsInspecting())
	require.False(t, chB.IsInspecting())
}
