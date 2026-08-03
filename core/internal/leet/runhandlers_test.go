package leet_test

import (
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// newRunForHandlerTest creates a Run model with sidebars expanded and
// seeded with enough data to exercise section navigation.
func newRunForHandlerTest(t *testing.T) *leet.Run {
	t.Helper()

	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetLeftSidebarVisible(true)
	_ = cfg.SetRightSidebarVisible(true)

	runParams := &leet.RunParams{
		RunFile: "testdata/fake.wandb",
	}
	r := leet.NewRun(runParams, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Force left sidebar expanded so section navigation is testable.
	r.TestForceExpandLeftSidebar()

	// Seed overview data to create focusable sections.
	r.TestHandleRecordMsg(leet.RunMsg{
		ID:      "abc123",
		Project: "test-project",
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.01"},
				{NestedKey: []string{"epochs"}, ValueJson: "10"},
			},
		},
	})
	r.TestHandleRecordMsg(leet.SummaryMsg{
		Summary: []*spb.SummaryRecord{{
			Update: []*spb.SummaryItem{
				{NestedKey: []string{"loss"}, ValueJson: "0.42"},
			},
		}},
	})
	r.TestHandleRecordMsg(leet.SystemInfoMsg{
		Record: &spb.EnvironmentRecord{WriterId: "w1", Os: "linux"},
	})

	// Ensure sidebar syncs the data.
	sidebar := r.TestGetLeftSidebar()
	sidebar.Sync()
	_ = sidebar.View(50)

	return r
}

// seedConsoleLog gives the console logs pane content so it is focusable.
func seedConsoleLog(r *leet.Run) {
	r.TestHandleRecordMsg(leet.ConsoleLogMsg{Text: "hello", Time: time.Now()})
}

// ---- handleSidebarTabNav ----

func TestRun_SidebarTabNav_BothPanelsVisible_CyclesOverviewThenLogs(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)
	seedConsoleLog(r)

	// Initial state: overview section 0 should be active.
	sidebar := r.TestGetLeftSidebar()
	require.True(t, r.TestLeftSidebarHasActiveSection(),
		"overview should start with an active section")
	require.False(t, r.TestConsoleLogsPaneActive(),
		"bottom bar should not be active initially")

	// Tab through overview sections until we reach the last one, then
	// Tab one more should jump to logs.
	_, lastSec := sidebar.TestFocusableSectionBounds()
	for r.TestLeftSidebarActiveSectionIdx() < lastSec {
		r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	require.Equal(t, lastSec, r.TestLeftSidebarActiveSectionIdx(),
		"should have reached last overview section")

	// One more Tab → logs.
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.True(t, r.TestConsoleLogsPaneActive(), "Tab past last section should focus logs")
	require.False(t, r.TestLeftSidebarHasActiveSection(),
		"overview sections should be deactivated when logs focused")

	// Tab from logs → overview first section.
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.False(t, r.TestConsoleLogsPaneActive(), "Tab from logs should leave logs")
	require.True(t, r.TestLeftSidebarHasActiveSection(), "should re-enter overview")
}

func TestRun_SidebarTabNav_OnlyLogsVisible(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)
	seedConsoleLog(r)
	r.TestForceCollapseLeftSidebar()

	// With overview collapsed, Tab should activate logs.
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.True(t, r.TestConsoleLogsPaneActive(),
		"Tab with collapsed overview should still reach logs")
}

func TestRun_SidebarTabNav_SkipsEmptyLogsPane(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)

	// The logs pane is open but has no content: Tab must skip it and
	// keep cycling overview sections.
	sidebar := r.TestGetLeftSidebar()
	_, lastSec := sidebar.TestFocusableSectionBounds()
	for r.TestLeftSidebarActiveSectionIdx() < lastSec {
		r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})

	require.False(t, r.TestConsoleLogsPaneActive(),
		"an empty logs pane must not receive focus")
	require.True(t, r.TestLeftSidebarHasActiveSection(),
		"focus should wrap back to the overview")
}

func TestRun_SidebarTabNav_OnlyOverviewVisible(t *testing.T) {
	r := newRunForHandlerTest(t)
	// Bottom bar collapsed (default).
	require.False(t, r.TestConsoleLogsPaneExpanded(), "bottom bar should start collapsed")

	// Tab should cycle through overview sections without reaching logs.
	initialSection := r.TestLeftSidebarActiveSectionIdx()
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	nextSection := r.TestLeftSidebarActiveSectionIdx()
	require.NotEqual(t, initialSection, nextSection,
		"Tab should cycle overview sections")
	require.False(t, r.TestConsoleLogsPaneActive(),
		"logs should never get focus when collapsed")
}

func TestRun_InitialFocus_PicksFirstAvailablePane(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetLeftSidebarVisible(false)
	_ = cfg.SetConsoleLogsVisible(true)

	r := leet.NewRun(&leet.RunParams{
		RunFile: "testdata/fake.wandb",
	}, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Focus is seeded once the first pane gains content.
	seedConsoleLog(r)

	require.True(t, r.TestConsoleLogsPaneActive(),
		"the first available pane should receive focus on load")
	require.False(t, r.TestLeftSidebarHasActiveSection(),
		"collapsed overview should not appear focused")
}

// ---- Mouse drag-resize of the sidebars ----

func TestRun_DragResizesRightSidebarAndPersists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetLeftSidebarVisible(true)
	_ = cfg.SetRightSidebarVisible(true)

	r := leet.NewRun(&leet.RunParams{RunFile: "testdata/fake.wandb"}, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	_, right0 := r.TestLayoutWidths()
	require.Positive(t, right0)

	// Press on the right sidebar's border column, drag 10 columns left
	// (widening the sidebar), release.
	borderX := 200 - right0
	r.Update(tea.MouseClickMsg{X: borderX, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: borderX - 10, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: borderX - 10, Y: 5, Button: tea.MouseLeft})

	_, right1 := r.TestLayoutWidths()
	require.Equal(t, right0+10, right1, "drag should widen the right sidebar")
	require.InDelta(t, float64(right0+10)/200.0, cfg.RunLayout().RightSidebar, 1e-9,
		"released drag should persist the width as a fraction of the terminal")

	// "0" resets the proportions and the persisted overrides.
	r.Update(tea.KeyPressMsg{Code: '0'})
	require.Equal(t, leet.LayoutOverrides{}, cfg.RunLayout())
	_, right2 := r.TestLayoutWidths()
	require.Equal(t, right0, right2, "reset should restore the default width")
}

// TestRun_RenderedSeparatorsAlignWithLayout pins the invariant that mouse
// hit-testing depends on: the separator rows drawn on screen sit exactly at
// the rows computeVerticalStackLayout reserves for them. The metrics grid
// renders header + rows*cellHeight lines, so without padding to the section
// height, everything below it (and its separators) drifts up by the integer
// division remainder.
func TestRun_RenderedSeparatorsAlignWithLayout(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetLeftSidebarVisible(false)
	_ = cfg.SetRightSidebarVisible(false)
	_ = cfg.SetMediaVisible(true)
	_ = cfg.SetConsoleLogsVisible(true)

	r := leet.NewRun(&leet.RunParams{RunFile: "testdata/fake.wandb"}, cfg, logger)
	// A height where the grid's cell height division leaves a remainder.
	r.Update(tea.WindowSizeMsg{Width: 120, Height: 52})
	r.TestHandleRecordMsg(leet.RunMsg{ID: "abc123", Project: "test-project"})
	r.TestHandleRecordMsg(leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1, 2}, Y: []float64{0.5, 0.4}},
		},
	})

	metrics, media, _ := r.TestStackHeights()
	lines := strings.Split(stripANSI(r.View().Content), "\n")

	for _, row := range []int{metrics, metrics + 1 + media} {
		require.Less(t, row, len(lines))
		require.True(t, strings.HasPrefix(strings.TrimSpace(lines[row]), "———"),
			"expected a separator at row %d, got %q", row, lines[row])
	}
}

func TestRun_DragSeparatorResizesMediaAndLogs(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetMediaVisible(true)
	_ = cfg.SetConsoleLogsVisible(true)

	r := leet.NewRun(&leet.RunParams{RunFile: "testdata/fake.wandb"}, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 200, Height: 100})

	metrics0, media0, logs0 := r.TestStackHeights()
	require.Positive(t, media0)
	require.Positive(t, logs0)

	// The separator above logs sits between two fixed panes (media above,
	// logs below). Drag it down 2 rows: media grows, logs shrinks.
	left0, _ := r.TestLayoutWidths()
	x := left0 + 5
	sepY := metrics0 + 1 + media0 + 1 - 1 // gap row above logs
	r.Update(tea.MouseClickMsg{X: x, Y: sepY, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: x, Y: sepY + 2, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: x, Y: sepY + 2, Button: tea.MouseLeft})

	metrics1, media1, logs1 := r.TestStackHeights()
	require.Equal(t, media0+2, media1, "pane above the separator should grow")
	require.Equal(t, logs0-2, logs1, "pane below the separator should shrink")
	require.Equal(t, metrics0, metrics1, "flex metrics grid should be untouched")

	// Both fractions persist on release.
	o := cfg.RunLayout()
	require.InDelta(t, float64(media1)/100.0, o.Media, 1e-9)
	require.InDelta(t, float64(logs1)/100.0, o.Logs, 1e-9)
}

// ---- Esc: unfocus pane first, exit view second ----

func TestRun_EscUnfocusesPane(t *testing.T) {
	r := newRunForHandlerTest(t)
	require.True(t, r.HasPaneFocus(), "seeded run should start with pane focus")

	r.Update(tea.KeyPressMsg{Code: tea.KeyEsc})

	require.False(t, r.HasPaneFocus(), "Esc should clear pane focus")
	require.False(t, r.TestLeftSidebarHasActiveSection(),
		"overview sections should be deactivated after Esc")
}

func TestRun_DataAfterEscDoesNotRestealFocus(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.False(t, r.HasPaneFocus())

	// More data arriving must not move focus once the user unfocused.
	r.TestHandleRecordMsg(leet.SummaryMsg{
		Summary: []*spb.SummaryRecord{{
			Update: []*spb.SummaryItem{
				{NestedKey: []string{"acc"}, ValueJson: "0.9"},
			},
		}},
	})
	require.False(t, r.HasPaneFocus(),
		"incoming data must not re-steal focus after Esc")
}

func TestModel_EscExitsRunViewOnlyWhenUnfocused(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	m := leet.NewModel(leet.ModelParams{
		RunParams: &leet.RunParams{RunFile: "testdata/fake.wandb"},
		Config:    cfg,
		Logger:    logger,
	})
	var tm tea.Model = m
	tm, _ = tm.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Seed overview data so focus lands on a pane.
	require.True(t, m.TestInRunMode())
	m.TestRunModel().TestHandleRecordMsg(leet.RunMsg{
		ID:      "abc123",
		Project: "test-project",
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.01"},
			},
		},
	})
	require.True(t, m.TestRunModel().HasPaneFocus())

	// First Esc unfocuses the pane but stays in the run view.
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.True(t, m.TestInRunMode(), "Esc with a focused pane must not exit the view")
	require.False(t, m.TestRunModel().HasPaneFocus())

	// Second Esc exits to the workspace.
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.False(t, m.TestInRunMode(), "Esc with no pane focus should exit to workspace")
	_ = tm
}

func TestRun_OverviewUpdatesPreserveTabContext(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetLeftSidebarVisible(true)

	r := leet.NewRun(&leet.RunParams{
		RunFile: "testdata/fake.wandb",
	}, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	r.TestHandleRecordMsg(leet.RunMsg{
		ID:      "abc123",
		Project: "test-project",
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.01"},
			},
		},
	})
	require.Equal(t, 1, r.TestLeftSidebarActiveSectionIdx(),
		"initial single-run focus should land on the first populated overview section")

	r.TestHandleRecordMsg(leet.SystemInfoMsg{
		Record: &spb.EnvironmentRecord{WriterId: "w1", Os: "linux"},
	})
	r.TestHandleRecordMsg(leet.SummaryMsg{
		Summary: []*spb.SummaryRecord{{
			Update: []*spb.SummaryItem{
				{NestedKey: []string{"loss"}, ValueJson: "0.42"},
			},
		}},
	})

	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.Equal(t, 2, r.TestLeftSidebarActiveSectionIdx(),
		"Tab should continue from Config to Summary after overview updates arrive")
}

// ---- Unified navigation: wasd/arrows aliasing + Home/End ----

func TestRun_UnifiedNav_OverviewUsesCanonicalKeys(t *testing.T) {
	r := newRunForHandlerTest(t)
	sidebar := r.TestGetLeftSidebar()
	before, _ := sidebar.SelectedItem()

	r.Update(primaryNavMsg(t, leet.NavIntentDown))
	afterPrimaryDown, _ := sidebar.SelectedItem()
	require.NotEmpty(t, before)
	require.NotEqual(t, before, afterPrimaryDown,
		"the primary down binding should move the overview selection")

	r.Update(primaryNavMsg(t, leet.NavIntentUp))
	require.Equal(t, before, mustSelectedItem(t, sidebar),
		"the primary up binding should undo the down move")

	r.Update(secondaryNavMsg(t, leet.NavIntentDown))
	require.Equal(t, afterPrimaryDown, mustSelectedItem(t, sidebar),
		"the secondary down binding should match the primary binding")

	r.Update(primaryNavMsg(t, leet.NavIntentHome))
	afterHome, _ := sidebar.SelectedItem()
	require.Equal(t, before, afterHome, "Home should return to the first item")

	r.Update(primaryNavMsg(t, leet.NavIntentEnd))
	afterEnd, _ := sidebar.SelectedItem()
	require.NotEqual(t, afterHome, afterEnd,
		"End should move the cursor away from the Home position")
}

func TestRun_UnifiedNav_GridUsesCanonicalDirectionalKeys(t *testing.T) {
	r := newRunForHandlerTest(t)

	// Seed enough metrics to form a 2x2 grid.
	r.TestHandleRecordMsg(leet.HistoryMsg{Metrics: map[string]leet.MetricData{
		"a": {X: []float64{1}, Y: []float64{1}},
		"b": {X: []float64{1}, Y: []float64{2}},
		"c": {X: []float64{1}, Y: []float64{3}},
		"d": {X: []float64{1}, Y: []float64{4}},
	}})

	// Focus the metrics grid.
	r.TestSetFocusTarget(int(leet.FocusTargetMetricsGrid))
	r.TestSetMainChartFocus(0, 0)

	focus := r.TestFocusState()
	require.Equal(t, leet.FocusMainChart, focus.Type)
	require.Equal(t, 0, focus.Row)
	require.Equal(t, 0, focus.Col)

	r.Update(primaryNavMsg(t, leet.NavIntentRight))
	require.Equal(t, 1, focus.Col,
		"the primary right binding should advance chart focus")

	r.TestSetMainChartFocus(0, 0)
	r.Update(secondaryNavMsg(t, leet.NavIntentRight))
	require.Equal(t, 1, focus.Col,
		"the secondary right binding should match the primary binding")

	r.TestSetMainChartFocus(0, 0)
	r.Update(secondaryNavMsg(t, leet.NavIntentDown))
	require.Equal(t, 1, focus.Row,
		"the secondary down binding should advance chart focus vertically")
}

func mustSelectedItem(t *testing.T, sidebar *leet.RunOverviewSidebar) string {
	t.Helper()
	key, _ := sidebar.SelectedItem()
	require.NotEmpty(t, key)
	return key
}
