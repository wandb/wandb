package leet

// Regression tests for fixes from the 2026-08 code review.

import (
	"path/filepath"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func summaryRecordsForTest(key, valueJSON string) []*spb.SummaryRecord {
	return []*spb.SummaryRecord{{
		Update: []*spb.SummaryItem{{NestedKey: []string{key}, ValueJson: valueJSON}},
	}}
}

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

// Ctrl+C must quit even while a filter input owns the keyboard.
func TestCtrlCQuitsDuringFilterInput(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "cfg.json"), logger)

	w := NewWorkspace(t.TempDir(), cfg, logger)
	w.handleWindowResize(200, 60)
	w.filter.Activate()
	if cmd := w.handleKeyPressMsg(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl}); cmd == nil {
		t.Fatal("workspace: ctrl+c in filter mode returned no command")
	}

	r := NewRun(&RunParams{RunFile: "unused"}, cfg, logger)
	r.metricsGrid.EnterFilterMode()
	if cmd := r.handleKeyPressMsg(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl}); cmd == nil {
		t.Fatal("run: ctrl+c in filter mode returned no command")
	}
}

// Sync must observe overview mutations made after a previous Sync
// (the sidebar skips syncs while the data generation is unchanged).
func TestRunOverviewSidebarSyncSeesNewData(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "cfg.json"), logger)

	ro := NewRunOverview()
	sb := NewRunOverviewSidebar(cfg, NewAnimatedValue(true, SidebarMinWidth), ro, SidebarSideLeft)

	ro.ProcessRunMsg(RunMsg{ID: "id-1", Project: "p"})
	sb.Sync()
	sb.Sync() // exercise the skip path

	ro.ProcessSummaryMsg(summaryRecordsForTest("loss", "0.5"))
	sb.Sync()

	if len(sb.sections[2].Items) == 0 {
		t.Fatal("summary section empty after post-sync mutation")
	}
}

// A same-size resize must not mark system charts dirty; the hosting views
// resize on every frame.
func TestTimeSeriesLineChartSameSizeResizeStaysClean(t *testing.T) {
	c := NewTimeSeriesLineChart(&TimeSeriesLineChartParams{
		Width:  40,
		Height: 10,
		Def:    &MetricDef{Name: "CPU (%)", Unit: UnitPercent, MaxY: 100},
		Now:    time.Now(),
	})
	c.AddDataPoint("cpu", time.Now().Unix(), 42)
	c.DrawIfNeeded()
	if c.dirty {
		t.Fatal("chart dirty after draw")
	}
	c.Resize(40, 10)
	if c.dirty {
		t.Fatal("same-size resize marked chart dirty")
	}
}

// Close must unblock the prepare command and be idempotent.
func TestMediaPaneCloseUnblocksPrepare(t *testing.T) {
	p := NewMediaPane(NewAnimatedValue(true, mediaPaneMinHeight), func() (int, int) { return 1, 1 })

	done := make(chan tea.Msg, 1)
	go func() { done <- p.waitForPrepare()() }()

	p.Close()
	p.Close() // idempotent

	select {
	case msg := <-done:
		if msg != nil {
			t.Fatalf("expected nil msg from closed prepare wait, got %T", msg)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("waitForPrepare still blocked after Close")
	}
}
