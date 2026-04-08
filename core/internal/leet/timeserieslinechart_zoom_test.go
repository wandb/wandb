package leet_test

import (
	"math"
	"path/filepath"
	"testing"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestTimeSeriesLineChart_AutoTrailFreezeAndShowAll(t *testing.T) {
	def := &leet.MetricDef{
		Name:      "CPU",
		Unit:      leet.UnitPercent,
		MinY:      0,
		MaxY:      100,
		AutoRange: true,
	}
	start := time.Unix(1_700_000_000, 0)

	chart := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		80,
		20,
		def,
		compat.AdaptiveColor{Light: lipgloss.Color("#FF00FF"), Dark: lipgloss.Color("#FF00FF")},
		stubColorProvider("#00FF00"),
		start,
	})
	chart.SetTailWindow(2 * time.Minute)

	for i := range 10 {
		ts := start.Add(time.Duration(i-9) * time.Minute)
		chart.AddDataPoint(leet.DefaultSystemMetricSeriesName, float64(ts.Unix()), float64(i))
	}

	viewMin, viewMax := chart.TestViewRange()
	require.True(t, chart.TestAutoTrail())
	require.InDelta(t, 120.0, viewMax-viewMin, 1.0, "tail window should default to 2 minutes")
	require.GreaterOrEqual(t, viewMax, float64(start.Unix()))

	chart.AddDataPoint(
		leet.DefaultSystemMetricSeriesName, float64(start.Add(time.Minute).Unix()), 10)
	trailMin, trailMax := chart.TestViewRange()
	require.True(t, chart.TestAutoTrail())
	require.Greater(t, trailMin, viewMin)
	require.Greater(t, trailMax, viewMax)

	for range 12 {
		if !chart.TestAutoTrail() {
			break
		}
		chart.HandleZoom("in", 0)
	}
	require.False(t, chart.TestAutoTrail(),
		"zooming away from the tail should freeze the view")
	frozenMin, frozenMax := chart.TestViewRange()

	chart.AddDataPoint(
		leet.DefaultSystemMetricSeriesName, float64(start.Add(2*time.Minute).Unix()), 11)
	stillMin, stillMax := chart.TestViewRange()
	require.InDelta(t, frozenMin, stillMin, 1e-9)
	require.InDelta(t, frozenMax, stillMax, 1e-9)

	for range 32 {
		if chart.TestShowAll() {
			break
		}
		chart.HandleZoom("out", chart.GraphWidth()/2)
	}
	require.True(t, chart.TestShowAll(),
		"zooming out should eventually show the full history")
	showAllMin, showAllMax := chart.TestViewRange()

	chart.AddDataPoint(
		leet.DefaultSystemMetricSeriesName, float64(start.Add(3*time.Minute).Unix()), 12)
	expandedMin, expandedMax := chart.TestViewRange()
	require.InDelta(t, showAllMin, expandedMin, 10,
		"full-history mode should preserve the start")
	require.Greater(t, expandedMax, showAllMax,
		"full-history mode should continue trailing live data")
	require.True(t, chart.TestAutoTrail())
}

func TestSystemMetricsGrid_MultiSeriesInspectionUsesTopmostSeries(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(1)
	_ = cfg.SetSystemCols(1)

	grid := leet.NewSystemMetricsGrid(
		2*leet.MinMetricChartWidth,
		2*leet.MinMetricChartHeight,
		cfg,
		cfg.SystemGrid,
		leet.NewFocus(),
		leet.NewFilter(),
		logger,
	)

	ts := time.Unix(1_700_000_000, 0).Unix()
	grid.AddDataPoint("gpu.0.temp", ts, 40)
	grid.AddDataPoint("gpu.1.temp", ts, 50)

	chart := grid.TestChartAt(0, 0)
	require.NotNil(t, chart)
	require.Equal(t, []string{"GPU 0", "GPU 1"}, chart.DrawOrder())

	chart.Draw()
	chart.InspectAtDataX(float64(ts))
	_, y, active := chart.InspectionData()
	require.True(t, active)
	require.InDelta(t, 50.0, y, 1e-9, "inspection should use the topmost series")
}

func computeSystemAdjustedX(
	t *testing.T,
	chart *leet.TimeSeriesLineChart,
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

func TestSystemMetricsGrid_Inspection_Synchronized(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(1)
	_ = cfg.SetSystemCols(2)

	grid := leet.NewSystemMetricsGrid(
		240,
		60,
		cfg,
		cfg.SystemGrid,
		leet.NewFocus(),
		leet.NewFilter(),
		logger,
	)

	base := time.Unix(1_700_000_000, 0)
	for i := range 6 {
		ts := base.Add(time.Duration(i) * time.Minute).Unix()
		grid.AddDataPoint("cpu.powerWatts", ts, 100+float64(i))
		grid.AddDataPoint("gpu.0.temp", ts, 40+float64(i))
	}
	grid.Resize(240, 60)

	dims := grid.TestGridDims()
	first := grid.TestChartAt(0, 0)
	second := grid.TestChartAt(0, 1)
	require.NotNil(t, first)
	require.NotNil(t, second)

	wantX := float64(base.Add(3 * time.Minute).Unix())
	relPX := int(math.Round(
		(wantX - first.ViewMinX()) / (first.ViewMaxX() - first.ViewMinX()) *
			float64(first.GraphWidth()),
	))
	adjX := computeSystemAdjustedX(t, first, dims.CellWWithPadding, 0, relPX)

	grid.StartInspection(adjX, 0, 0, 0, dims, true)
	require.True(t, grid.TestSyncInspectActive())

	xA, _, aActive := first.InspectionData()
	xB, _, bActive := second.InspectionData()
	require.True(t, aActive)
	require.True(t, bActive)
	require.InDelta(t, wantX, xA, 1e-9)
	require.InDelta(t, wantX, xB, 1e-9)

	wantX = float64(base.Add(5 * time.Minute).Unix())
	relPX = int(math.Round(
		(wantX - first.ViewMinX()) / (first.ViewMaxX() - first.ViewMinX()) *
			float64(first.GraphWidth()),
	))
	adjX = computeSystemAdjustedX(t, first, dims.CellWWithPadding, 0, relPX)
	grid.UpdateInspection(adjX, 0, 0, 0, dims)

	xA, _, _ = first.InspectionData()
	xB, _, _ = second.InspectionData()
	require.InDelta(t, wantX, xA, 1e-9)
	require.InDelta(t, wantX, xB, 1e-9)

	grid.EndInspection()
	require.False(t, grid.TestSyncInspectActive())
	require.False(t, first.IsInspecting())
	require.False(t, second.IsInspecting())
}
