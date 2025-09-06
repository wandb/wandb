package leet

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
)

func useTestConfig(t *testing.T, rows, cols int) {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	cfg := GetConfig()
	cfg.SetPathForTests(path)
	// Load to ensure the directory/file exists (save creates the dir).
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	if err := cfg.SetSystemRows(rows); err != nil {
		t.Fatalf("SetSystemRows: %v", err)
	}
	if err := cfg.SetSystemCols(cols); err != nil {
		t.Fatalf("SetSystemCols: %v", err)
	}
	// Propagate into MetricsGridRows/MetricsGridCols, etc.
	UpdateGridDimensions()
}

func TestRightSidebar_ProcessStatsMsg_GroupsSeriesByBaseKey(t *testing.T) {
	// Avoid t.Parallel(): global config + package-level grid dims are mutated.
	useTestConfig(t, 2, 2)

	logger := observability.NewNoOpLogger()
	rs := NewRightSidebar(logger)

	ts := time.Now().Unix()
	rs.ProcessStatsMsg(StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"gpu.1.temp":        42,
			"cpu.0.cpu_percent": 50,
		},
	})

	if rs.metricsGrid == nil {
		t.Fatal("metricsGrid not created")
	}
	if got, want := rs.metricsGrid.GetChartCount(), 2; got != want {
		t.Fatalf("GetChartCount()=%d; want %d", got, want)
	}

	// gpu.* temps should share one chart with multiple series.
	gpuChart := rs.metricsGrid.chartsByMetric["gpu.temp"]
	if gpuChart == nil {
		t.Fatalf("gpu.temp chart missing")
	}
	if got, want := len(gpuChart.series), 2; got != want {
		t.Fatalf("gpu.temp series=%d; want %d", got, want)
	}

	// Add a third GPU series; should not create a new chart, only new series.
	rs.ProcessStatsMsg(StatsMsg{
		Timestamp: ts + 1,
		Metrics:   map[string]float64{"gpu.2.temp": 43},
	})
	if got, want := len(gpuChart.series), 3; got != want {
		t.Fatalf("gpu.temp series=%d; want %d", got, want)
	}

	// Unknown metrics are ignored (no chart created).
	rs.ProcessStatsMsg(StatsMsg{
		Timestamp: ts + 2,
		Metrics:   map[string]float64{"unknown.metric": 1},
	})
	if _, ok := rs.metricsGrid.chartsByMetric["unknown.metric"]; ok {
		t.Fatalf("unexpected chart created for unknown.metric")
	}
}

func TestSystemMetricsGrid_Reset(t *testing.T) {
	// Avoid t.Parallel(): global config + package-level grid dims are mutated.
	useTestConfig(t, 2, 2)

	logger := observability.NewNoOpLogger()
	// Give the grid enough space (any positive multiples will do).
	grid := NewSystemMetricsGrid(2*MinMetricChartWidth, 2*MinMetricChartHeight, logger)

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
