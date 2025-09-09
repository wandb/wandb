package leet_test

import (
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func useTestConfig(t *testing.T, rows, cols int) {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	cfg := leet.GetConfig()
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
	leet.UpdateGridDimensions()
}

func TestRightSidebar_ProcessStatsMsg_GroupsSeriesByBaseKey(t *testing.T) {
	// Avoid t.Parallel(): global config + package-level grid dims are mutated.
	useTestConfig(t, 2, 2)

	logger := observability.NewNoOpLogger()
	rs := leet.NewRightSidebar(logger)

	// Give the sidebar real dimensions and expand it so View() renders charts.
	rs.UpdateDimensions(200, false)
	rs.Toggle()
	time.Sleep(leet.AnimationDuration + 20*time.Millisecond)
	// Finish animation.
	rs.Update(leet.RightSidebarAnimationMsg{})

	ts := time.Now().Unix()
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"gpu.1.temp":        42,
			"cpu.0.cpu_percent": 50,
		},
	})

	// Expect two charts total; "GPU Temp (°C)" shows two series.
	out := rs.View(30)
	if !strings.Contains(out, "GPU Temp (°C) [2]") {
		t.Fatalf("expected GPU Temp with [2] series; got:\n%s", out)
	}
	if !strings.Contains(out, "of 2]") { // nav info shows total chart count
		t.Fatalf("expected nav info 'of 2' in view; got:\n%s", out)
	}

	// Add a third GPU series; should increase series count, not create a new chart.
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts + 1,
		Metrics:   map[string]float64{"gpu.2.temp": 43},
	})
	out = rs.View(30)
	if !strings.Contains(out, "GPU Temp (°C) [3]") {
		t.Fatalf("expected GPU Temp with [3] series; got:\n%s", out)
	}

	// Unknown metrics are ignored (no extra chart).
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts + 2,
		Metrics:   map[string]float64{"unknown.metric": 1},
	})
	out = rs.View(30)
	if !strings.Contains(out, "of 2]") {
		t.Fatalf("unexpected chart count change after unknown metric; got:\n%s", out)
	}
}

func TestSystemMetricsGrid_Reset(t *testing.T) {
	// Avoid t.Parallel(): global config + package-level grid dims are mutated.
	useTestConfig(t, 2, 2)

	logger := observability.NewNoOpLogger()
	// Give the grid enough space (any positive multiples will do).
	grid := leet.NewSystemMetricsGrid(2*leet.MinMetricChartWidth, 2*leet.MinMetricChartHeight, logger)

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
