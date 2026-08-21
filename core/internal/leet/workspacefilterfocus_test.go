package leet

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// The shared system-metrics filter must be reapplied to a run's grid when the
// highlighted run changes; each grid caches its own filtered chart set.
func TestWorkspaceSystemFilterReappliedOnRunSwitch(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "cfg.json"), logger)
	w := NewWorkspace(t.TempDir(), cfg, logger)
	w.handleWindowResize(200, 60)

	stats := StatsMsg{Timestamp: 1, Metrics: map[string]float64{
		"cpu":                   12.0,
		"gpu.0.memoryAllocated": 40.0,
	}}
	gridA := w.getOrCreateSystemMetricsGrid("run-a")
	gridA.ProcessStats(stats)
	gridB := w.getOrCreateSystemMetricsGrid("run-b")
	gridB.ProcessStats(stats)

	// Apply a filter while run A's grid is active.
	w.systemMetricsFilter.Activate()
	w.systemMetricsFilter.UpdateDraft(tea.KeyPressMsg{Code: 'g', Text: "gpu"})
	w.systemMetricsFilter.Commit()
	gridA.ApplyFilter()

	if gridA.FilteredChartCount() == gridA.ChartCount() {
		t.Fatalf("filter had no effect on grid A")
	}
	if gridB.FilteredChartCount() != gridB.ChartCount() {
		t.Fatalf("grid B unexpectedly pre-filtered")
	}

	// Highlight run B; the sync path must reapply the shared filter to B's
	// grid, which caches its own filtered chart set.
	w.currentSystemGrid = gridA
	w.runs.Items = []KeyValuePair{{Key: "run-b"}}
	w.runs.FilteredItems = w.runs.Items
	w.syncCurrentRunContext()

	if gridB.FilteredChartCount() != gridA.FilteredChartCount() {
		t.Fatalf("grid B filtered=%d, want %d after switch",
			gridB.FilteredChartCount(), gridA.FilteredChartCount())
	}
}
