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

	focusState := &leet.Focus{}
	// Give the grid enough space (any positive multiples will do).
	grid := leet.NewSystemMetricsGrid(
		2*leet.MinMetricChartWidth,
		2*leet.MinMetricChartHeight,
		cfg,
		focusState,
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
	focusState := &leet.Focus{}
	grid := leet.NewSystemMetricsGrid(gridWidth, gridHeight, cfg, focusState, logger)

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

func TestSystemMetricsGrid_NavigateWithPowerMetrics(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_, _ = cfg.SetSystemRows(2), cfg.SetSystemCols(1)
	gridRows, gridCols := cfg.SystemGrid()

	gridWidth := leet.MinMetricChartWidth * gridCols * 2
	gridHeight := leet.MinMetricChartHeight * gridRows * 2
	focusState := &leet.Focus{}
	grid := leet.NewSystemMetricsGrid(gridWidth, gridHeight, cfg, focusState, logger)

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

	// Verify focus is cleared after navigation
	grid.HandleMouseClick(0, 0) // Focus a chart
	require.NotEmpty(t, grid.FocusedChartTitle(), "chart should be focused before navigation")

	grid.Navigate(1)
	require.Empty(t, grid.FocusedChartTitle(), "focus should be cleared after navigation")
}
