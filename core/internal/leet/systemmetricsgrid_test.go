package leet_test

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSystemMetricsGrid(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_, _ = cfg.SetSystemRows(2), cfg.SetSystemCols(1)

	focus := leet.NewFocus()
	filter := leet.NewFilter()
	// Give the grid enough space (any positive multiples will do).
	grid := leet.NewSystemMetricsGrid(
		2*leet.MinMetricChartWidth,
		2*leet.MinMetricChartHeight,
		cfg,
		cfg.SystemGrid,
		focus,
		filter,
		logger,
	)

	ts := time.Now().Unix()
	grid.AddDataPoint("gpu.0.temp", ts, 50)
	grid.AddDataPoint("gpu.1.temp", ts, 55)

	require.NotZero(t, grid.ChartCount(), "expected charts after AddDataPoint")
}

func TestSystemMetricsGrid_FocusToggleAndRebuild(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_, _ = cfg.SetSystemRows(2), cfg.SetSystemCols(1)
	gridRows, gridCols := cfg.SystemGrid()

	// Create grid with sufficient size
	gridWidth := leet.MinMetricChartWidth * gridCols * 2
	gridHeight := leet.MinMetricChartHeight * gridRows * 2
	focus := leet.NewFocus()
	filter := leet.NewFilter()
	grid := leet.NewSystemMetricsGrid(
		gridWidth, gridHeight, cfg, cfg.SystemGrid, focus, filter, logger)

	ts := time.Now().Unix()
	// Add multiple data points to ensure chart is properly created and visible
	grid.AddDataPoint("gpu.0.temp", ts, 40)
	grid.AddDataPoint("gpu.0.temp", ts+1, 41)
	grid.AddDataPoint("gpu.0.temp", ts+2, 42)

	grid.LoadCurrentPage()

	// Verify chart was created
	require.Equal(t, 1, grid.ChartCount())

	// First click should focus (charts array is populated by AddDataPoint)
	ok := grid.HandleMouseClick(0, 0)
	require.True(t, ok, "expected focus after first click")

	// Second click on same cell should unfocus
	ok2 := grid.HandleMouseClick(0, 0)
	require.False(t, ok2, "expected unfocus (toggle off) after second click")

	grid.ClearFocus()

	// Add more data after rebuild
	grid.AddDataPoint("gpu.0.temp", ts+3, 43)

	// Should be able to focus again after rebuild
	ok3 := grid.HandleMouseClick(0, 0)
	require.True(t, ok3, "expected to be able to focus after rebuild")
}

func TestSystemMetricsGrid_ResizeAfterGridConfigChange(t *testing.T) {
	for _, axis := range []string{"rows", "cols"} {
		t.Run(axis, func(t *testing.T) {
			logger := observability.NewNoOpLogger()
			cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
			require.NoError(t, cfg.SetSystemRows(1))
			require.NoError(t, cfg.SetSystemCols(1))
			setSize := cfg.SetSystemRows
			if axis == "cols" {
				setSize = cfg.SetSystemCols
			}
			require.NoError(t, setSize(2))

			const width, height = 180, 60
			focus := leet.NewFocus()
			grid := leet.NewSystemMetricsGrid(
				width, height, cfg, cfg.SystemGrid, focus, leet.NewFilter(), logger)
			grid.ProcessStats(leet.StatsMsg{
				Timestamp: time.Now().Unix(),
				Metrics: map[string]float64{
					"ane.power":         15,
					"cpu.powerWatts":    25,
					"gpu.0.powerWatts":  150,
					"system.powerWatts": 350,
				},
			})
			require.Equal(t, 4, grid.ChartCount())
			grid.NavigateEnd()
			require.Equal(t, 1, grid.TestNavigatorCurrentPage())
			focusedTitle := grid.FocusedChartTitle()
			require.NotEmpty(t, focusedTitle)

			checkLayout := func() {
				t.Helper()
				require.NotPanics(t, func() { grid.View() })
				rows, cols := cfg.SystemGrid()
				page := grid.TestCurrentPage()
				require.Len(t, page, rows)
				dims := leet.ComputeGridDims(width, height, leet.GridSpec{
					Rows: rows, Cols: cols,
					MinCellW: leet.MinMetricChartWidth,
					MinCellH: leet.MinMetricChartHeight,
				})
				for _, row := range page {
					require.Len(t, row, cols)
					for _, chart := range row {
						require.NotNil(t, chart)
						require.Equal(t, dims.CellW, chart.Width())
						require.Equal(t, dims.CellH, chart.Height())
					}
				}
			}

			// Growing the grid in the same viewport collapses two pages into one.
			require.NoError(t, setSize(4))
			grid.Resize(width, height)
			checkLayout()
			require.Zero(t, grid.TestNavigatorCurrentPage())
			require.Equal(t, focusedTitle, grid.FocusedChartTitle())
			require.Equal(t, focusedTitle, grid.TestChartAt(focus.Row, focus.Col).Title())

			// Shrinking must resize charts and restore pagination as well.
			require.NoError(t, setSize(1))
			grid.Resize(width, height)
			checkLayout()
			require.Empty(t, grid.FocusedChartTitle(), "focused chart left the visible page")
			grid.NavigateEnd()
			require.Equal(t, 3, grid.TestNavigatorCurrentPage())
			checkLayout()
		})
	}
}

func TestSystemMetricsGrid_NavigateWithPowerMetrics(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_, _ = cfg.SetSystemRows(2), cfg.SetSystemCols(1)
	gridRows, gridCols := cfg.SystemGrid()

	gridWidth := leet.MinMetricChartWidth * gridCols * 2
	gridHeight := leet.MinMetricChartHeight * gridRows * 2
	focus := leet.NewFocus()
	filter := leet.NewFilter()
	grid := leet.NewSystemMetricsGrid(
		gridWidth, gridHeight, cfg, cfg.SystemGrid, focus, filter, logger)

	ts := time.Now().Unix()

	// Add metrics across multiple pages
	grid.AddDataPoint("cpu.powerWatts", ts, 25.5)
	grid.AddDataPoint("gpu.0.powerWatts", ts, 150.0)
	grid.AddDataPoint("gpu.1.powerWatts", ts, 145.5)
	grid.AddDataPoint("system.powerWatts", ts, 350.0)
	grid.AddDataPoint("ane.power", ts, 15.0)
	grid.AddDataPoint("gpu.2.powerWatts", ts, 160.0)

	// Verify initial state
	grid.LoadCurrentPage()
	require.Equal(t, 4, grid.ChartCount())

	// Test navigation forward
	initialCharts := grid.TestCurrentPage()
	var firstPageChart *leet.TimeSeriesLineChart
	if initialCharts[0][0] != nil {
		firstPageChart = initialCharts[0][0]
	}

	grid.Navigate(1) // Move to page 2
	grid.LoadCurrentPage()

	secondPageCharts := grid.TestCurrentPage()
	var secondPageChart *leet.TimeSeriesLineChart
	if secondPageCharts[0][0] != nil {
		secondPageChart = secondPageCharts[0][0]
	}

	// Verify page changed (different charts)
	if firstPageChart != nil && secondPageChart != nil {
		require.NotEqual(t,
			firstPageChart,
			secondPageChart,
			"navigation did not change displayed charts",
		)
	}

	// Test navigation backward (wrap around)
	grid.Navigate(-1) // Back to page 1
	grid.LoadCurrentPage()

	// Test wrap-around navigation
	grid.Navigate(-1) // Should wrap to last page
	grid.LoadCurrentPage()

	// Navigate forward multiple times to test full cycle
	for range 3 {
		grid.Navigate(1)
		grid.LoadCurrentPage()
	}

	// Navigate auto-focuses the first chart on the new page.
	grid.Navigate(1)
	require.NotEmpty(t, grid.FocusedChartTitle(), "first chart should be focused after navigation")
}
