package leet_test

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSystemMetricsGrid_Reset(t *testing.T) {
	// Avoid t.Parallel(): global config + package-level grid dims are mutated.
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	_ = cfg.SetSystemRows(2)
	_ = cfg.SetSystemCols(2)

	logger := observability.NewNoOpLogger()
	// Give the grid enough space (any positive multiples will do).
	grid := leet.NewSystemMetricsGrid(2*leet.MinMetricChartWidth, 2*leet.MinMetricChartHeight, cfg, logger)

	ts := time.Now().Unix()
	grid.AddDataPoint("gpu.0.temp", ts, 50)
	grid.AddDataPoint("gpu.1.temp", ts, 55)

	if got := grid.GetChartCount(); got == 0 {
		t.Fatalf("expected charts after AddDataPoint, got %d", got)
	}

	grid.Reset()
	if got := grid.GetChartCount(); got != 0 {
		t.Fatalf("GetChartCount()=%d after Reset; want 0", got)
	}
}

func TestRightSidebar_ProcessStatsMsg_GroupsSeriesByBaseKey(t *testing.T) {
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	_ = cfg.SetSystemRows(2)
	_ = cfg.SetSystemCols(2)

	logger := observability.NewNoOpLogger()
	rs := leet.NewRightSidebar(cfg, logger)

	ts := time.Now().Unix()
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"gpu.1.temp":        42,
			"cpu.0.cpu_percent": 50,
		},
	})

	if got, want := rs.TestGetChartCount(), 2; got != want {
		t.Fatalf("chartCount=%d; want %d", got, want)
	}

	gpuChart := rs.TestMetricsChart("gpu.temp")
	if gpuChart == nil {
		t.Fatalf("gpu.temp chart missing")
	}
	if got, want := gpuChart.TestSeriesCount(), 2; got != want {
		t.Fatalf("gpu.temp series=%d; want %d", got, want)
	}

	// Add a third GPU series
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts + 1,
		Metrics:   map[string]float64{"gpu.2.temp": 43},
	})
	if got, want := gpuChart.TestSeriesCount(), 3; got != want {
		t.Fatalf("gpu.temp series=%d; want %d", got, want)
	}

	// Unknown metrics are ignored
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts + 2,
		Metrics:   map[string]float64{"unknown.metric": 1},
	})
	if rs.TestMetricsChart("unknown.metric") != nil {
		t.Fatalf("unexpected chart created for unknown.metric")
	}
}

// --- System metrics grid focus ---
func TestSystemMetricsGrid_FocusToggleAndRebuild(t *testing.T) {
	cfgPath := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.GetConfig()
	cfg.SetPathForTests(cfgPath)
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	_ = cfg.SetSystemRows(2)
	_ = cfg.SetSystemCols(2)
	gridRows, gridCols := cfg.GetSystemGrid()

	logger := observability.NewNoOpLogger()
	// Create grid with sufficient size
	gridWidth := leet.MinMetricChartWidth * gridCols * 2
	gridHeight := leet.MinMetricChartHeight * gridRows * 2
	grid := leet.NewSystemMetricsGrid(gridWidth, gridHeight, cfg, logger)

	ts := time.Now().Unix()
	// Add multiple data points to ensure chart is properly created and visible
	grid.AddDataPoint("gpu.0.temp", ts, 40)
	grid.AddDataPoint("gpu.0.temp", ts+1, 41)
	grid.AddDataPoint("gpu.0.temp", ts+2, 42)

	grid.LoadCurrentPage()

	// Verify chart was created
	if grid.GetChartCount() != 1 {
		t.Fatalf("expected 1 chart, got %d", grid.GetChartCount())
	}

	// First click should focus (charts array is populated by AddDataPoint)
	ok := grid.HandleMouseClick(0, 0)
	if !ok {
		t.Fatalf("expected focus after first click")
	}

	// Second click on same cell should unfocus
	ok2 := grid.HandleMouseClick(0, 0)

	if ok2 {
		t.Fatalf("expected unfocus (toggle off) after second click")
	}

	// Rebuild clears focus
	grid.RebuildGrid()

	// Add more data after rebuild
	grid.AddDataPoint("gpu.0.temp", ts+3, 43)

	// Should be able to focus again after rebuild
	ok3 := grid.HandleMouseClick(0, 0)
	if !ok3 {
		t.Fatalf("expected to be able to focus after rebuild")
	}
}

func TestSystemMetricsGrid_NavigateWithPowerMetrics(t *testing.T) {
	// Setup config
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	if err := cfg.SetSystemRows(1); err != nil {
		t.Fatalf("SetSystemRows: %v", err)
	}
	if err := cfg.SetSystemCols(1); err != nil {
		t.Fatalf("SetSystemCols: %v", err)
	}

	gridRows, gridCols := cfg.GetSystemGrid()

	logger := observability.NewNoOpLogger()
	gridWidth := leet.MinMetricChartWidth * gridCols * 2
	gridHeight := leet.MinMetricChartHeight * gridRows * 2
	grid := leet.NewSystemMetricsGrid(gridWidth, gridHeight, cfg, logger)

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
	if got, want := grid.GetChartCount(), 4; got != want {
		t.Fatalf("expected %d charts, got %d", want, got)
	}

	// Test navigation forward
	initialCharts := grid.GetCharts()
	var firstPageChart *leet.SystemMetricChart
	if initialCharts[0][0] != nil {
		firstPageChart = initialCharts[0][0]
	}

	grid.Navigate(1) // Move to page 2
	grid.LoadCurrentPage()

	secondPageCharts := grid.GetCharts()
	var secondPageChart *leet.SystemMetricChart
	if secondPageCharts[0][0] != nil {
		secondPageChart = secondPageCharts[0][0]
	}

	// Verify page changed (different charts)
	if firstPageChart != nil && secondPageChart != nil {
		if firstPageChart == secondPageChart {
			t.Fatal("navigation did not change displayed charts")
		}
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
	if grid.GetFocusedChartTitle() == "" {
		t.Fatal("chart should be focused before navigation")
	}

	grid.Navigate(1)
	if grid.GetFocusedChartTitle() != "" {
		t.Fatal("focus should be cleared after navigation")
	}
}
