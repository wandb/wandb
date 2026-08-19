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

// newTestRun builds an unseeded Run at the given terminal size, with config
// tweaks applied before construction.
func newTestRun(
	t *testing.T, width, height int, tweak func(*leet.ConfigManager),
) (*leet.Run, *leet.ConfigManager) {
	t.Helper()
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	if tweak != nil {
		tweak(cfg)
	}
	r := leet.NewRun(&leet.RunParams{RunFile: "testdata/fake.wandb"}, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: width, Height: height})
	return r, cfg
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

// ---- Mouse drag-resize ----

func TestRun_DragResizesRightSidebarAndPersists(t *testing.T) {
	r, cfg := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetLeftSidebarVisible(true)
		_ = c.SetRightSidebarVisible(true)
	})

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

func TestRun_DragSidebarKeepsMainColumnUsable(t *testing.T) {
	r, _ := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetLeftSidebarVisible(true)
		_ = c.SetRightSidebarVisible(true)
	})

	// Drag the left sidebar border all the way into the right sidebar.
	left0, _ := r.TestLayoutWidths()
	r.Update(tea.MouseClickMsg{X: left0 - 1, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: 195, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: 195, Y: 5, Button: tea.MouseLeft})

	// The main content column keeps its minimum width; the sidebars never
	// overlap it or each other.
	left1, right1 := r.TestLayoutWidths()
	require.GreaterOrEqual(t, 200-left1-right1, 24,
		"dragging a sidebar must leave room for the main content column")
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

// newModelInRunMode builds the top-level model in run mode at 200x60, with
// config tweaks applied before construction.
func newModelInRunMode(
	t *testing.T, tweak func(*leet.ConfigManager),
) (*leet.Model, tea.Model) {
	t.Helper()
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	if tweak != nil {
		tweak(cfg)
	}
	m := leet.NewModel(leet.ModelParams{
		RunParams: &leet.RunParams{RunFile: "testdata/fake.wandb"},
		Config:    cfg,
		Logger:    logger,
	})
	var tm tea.Model = m
	tm, _ = tm.Update(tea.WindowSizeMsg{Width: 200, Height: 60})
	require.True(t, m.TestInRunMode())
	return m, tm
}

// seedOverview gives the run overview config data so a pane takes focus.
func seedOverview(r *leet.Run) {
	r.TestHandleRecordMsg(leet.RunMsg{
		ID:      "abc123",
		Project: "test-project",
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.01"},
			},
		},
	})
}

func TestModel_EscExitsRunViewOnlyWhenUnfocused(t *testing.T) {
	m, tm := newModelInRunMode(t, nil)
	seedOverview(m.TestRunModel())
	require.True(t, m.TestRunModel().HasPaneFocus())

	// First Esc unfocuses the pane but stays in the run view.
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.True(t, m.TestInRunMode(), "Esc with a focused pane must not exit the view")
	require.False(t, m.TestRunModel().HasPaneFocus())

	// Second Esc exits to the workspace.
	_, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.False(t, m.TestInRunMode(), "Esc with no pane focus should exit to workspace")
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

// TestRun_StackSectionsAlignWithReservedRows pins the invariant that mouse
// hit-testing depends on: the separator rows drawn on screen sit exactly at
// the rows computeVerticalStackLayout reserves for them, and the frame never
// grows taller than the terminal. The metrics section must pad a short
// render (integer-division remainder) and crop a tall one (grid minimum or
// empty-state hint taller than the slot — lipgloss.Place never crops).
func TestRun_StackSectionsAlignWithReservedRows(t *testing.T) {
	for _, tc := range []struct {
		name       string
		height     int
		hasMetrics bool
	}{
		{"grid height leaves a division remainder", 52, true},
		{"grid minimum is taller than its slot", 20, true},
		{"empty-state hint is taller than its slot", 17, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, _ := newTestRun(t, 120, tc.height, func(c *leet.ConfigManager) {
				_ = c.SetLeftSidebarVisible(false)
				_ = c.SetRightSidebarVisible(false)
				_ = c.SetMediaVisible(true)
				_ = c.SetConsoleLogsVisible(true)
			})
			r.TestHandleRecordMsg(leet.RunMsg{ID: "abc123", Project: "test-project"})
			if tc.hasMetrics {
				r.TestHandleRecordMsg(leet.HistoryMsg{
					Metrics: map[string]leet.MetricData{
						"loss": {X: []float64{1, 2}, Y: []float64{0.5, 0.4}},
					},
				})
			}

			metrics, media, _ := r.TestStackHeights()
			require.Positive(t, metrics)
			lines := strings.Split(stripANSI(r.View().Content), "\n")
			require.LessOrEqual(t, len(lines), tc.height,
				"the rendered frame must never be taller than the terminal")

			for _, row := range []int{metrics, metrics + 1 + media} {
				require.Less(t, row, len(lines))
				require.True(t, strings.HasPrefix(strings.TrimSpace(lines[row]), "———"),
					"expected a separator at row %d, got %q", row, lines[row])
			}
		})
	}
}

// Regression: Tab while the media pane was fullscreen used to move focus away
// with fullscreen left on; Esc then cleared the invisible focus once and every
// further press was captured by the fullscreen guard with no way out.
// Fullscreen now follows focus.
func TestModel_TabWhileMediaFullscreenExitsFullscreen(t *testing.T) {
	m, tm := newModelInRunMode(t, func(c *leet.ConfigManager) {
		_ = c.SetMediaVisible(true)
	})

	// Metrics + media data: focus seeds on the metrics grid, media is the
	// next available region.
	r := m.TestRunModel()
	r.TestHandleRecordMsg(leet.RunMsg{ID: "abc123", Project: "test-project"})
	r.TestHandleRecordMsg(leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1, 2}, Y: []float64{0.5, 0.4}},
		},
		Media: map[string][]leet.MediaPoint{
			"media/img": {{X: 1, FilePath: "a.png", Format: "png"}},
		},
	})
	require.True(t, r.HasPaneFocus())

	// Tab to the media pane, enter fullscreen, then Tab away.
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	require.True(t, r.MediaFullscreen())
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.False(t, r.MediaFullscreen(), "fullscreen must follow focus")

	// Esc still peels one layer at a time: focus, then the view.
	tm, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.True(t, m.TestInRunMode())
	require.False(t, r.HasPaneFocus())
	_, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.False(t, m.TestInRunMode())
}

// Regression: a fast Esc-Esc mash reaches the app as one alt+esc; the keyMap
// missed it while the model exit was suppressed by the focus snapshot, so the
// press did nothing.
func TestModel_ModifiedEscStillPeelsFocus(t *testing.T) {
	m, tm := newModelInRunMode(t, func(c *leet.ConfigManager) {
		_ = c.SetLeftSidebarVisible(true)
	})
	seedOverview(m.TestRunModel())
	require.True(t, m.TestRunModel().HasPaneFocus())

	_, _ = tm.Update(tea.KeyPressMsg{Code: tea.KeyEsc, Mod: tea.ModAlt})
	require.False(t, m.TestRunModel().HasPaneFocus(),
		"a modified Esc must still unfocus the pane")
	require.True(t, m.TestInRunMode(),
		"a modified Esc must not also exit the view")
}

// Regression: an explicit Esc-unfocus before the one-time focus seed fired
// used to be overridden by the next incoming record re-seeding focus.
func TestRun_EscBeforeSeedStopsDataFromStealingFocus(t *testing.T) {
	r, _ := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetMediaVisible(true)
	})

	// Media data arrives via the shared store, not a record, so the seed has
	// not fired yet; the user tabs in and explicitly unfocuses.
	store := leet.NewMediaStore()
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"media/img": {{X: 1, FilePath: "a.png", Format: "png"}},
		},
	})
	r.SetMediaStore(store)
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.True(t, r.HasPaneFocus())
	r.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.False(t, r.HasPaneFocus())

	// The first processed record must not move focus back.
	r.TestHandleRecordMsg(leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1, 2}, Y: []float64{0.5, 0.4}},
		},
	})
	require.False(t, r.HasPaneFocus(),
		"data after an explicit unfocus must not re-seed focus")
}

// Regression: individually legal pane-height overrides (media 0.5 + logs 0.5)
// used to overflow the terminal vertically, pushing the status bar off-screen
// and desyncing mouse hit-testing from the rendered rows.
func TestRun_StackOverridesNeverOverflowFrame(t *testing.T) {
	r, _ := newTestRun(t, 120, 50, func(c *leet.ConfigManager) {
		_ = c.SetMediaVisible(true)
		_ = c.SetConsoleLogsVisible(true)
		_ = c.SetLeftSidebarVisible(false)
		_ = c.SetRightSidebarVisible(false)
		require.NoError(t, c.SetRunLayout(leet.LayoutOverrides{Media: 0.5, Logs: 0.5}))
	})
	r.TestHandleRecordMsg(leet.RunMsg{ID: "abc123", Project: "test-project"})
	r.TestHandleRecordMsg(leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1, 2}, Y: []float64{0.5, 0.4}},
		},
	})

	// The short terminal exercises the interplay with the panes' own
	// minimum heights, which re-inflate a naive proportional fit.
	for _, height := range []int{50, 24} {
		r.Update(tea.WindowSizeMsg{Width: 120, Height: height})

		lines := strings.Split(r.View().Content, "\n")
		require.LessOrEqual(t, len(lines), height,
			"the rendered frame must never be taller than the terminal (h=%d)", height)

		metrics, _, _ := r.TestStackHeights()
		require.GreaterOrEqual(t, metrics, 5, // minFlexMetricsHeight
			"overridden fixed panes must not squeeze the metrics section out (h=%d)", height)
	}
}

// Regression: '0' pressed mid-drag used to be silently overwritten when the
// release persisted the pre-reset drag values.
func TestRun_ZeroKeyMidDragWins(t *testing.T) {
	r, cfg := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetRightSidebarVisible(true)
	})

	_, right0 := r.TestLayoutWidths()
	borderX := 200 - right0
	r.Update(tea.MouseClickMsg{X: borderX, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: borderX - 10, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.KeyPressMsg{Code: '0'})
	r.Update(tea.MouseReleaseMsg{X: borderX - 10, Y: 5, Button: tea.MouseLeft})

	require.Equal(t, leet.LayoutOverrides{}, cfg.RunLayout(),
		"the reset must win over the in-flight drag")
	_, right1 := r.TestLayoutWidths()
	require.Equal(t, right0, right1, "the layout must return to the default")
}

// Regression: a release of a different button used to end (and persist) a
// left-button drag mid-gesture.
func TestRun_RightReleaseDoesNotEndLeftDrag(t *testing.T) {
	r, cfg := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetRightSidebarVisible(true)
	})

	_, right0 := r.TestLayoutWidths()
	borderX := 200 - right0
	r.Update(tea.MouseClickMsg{X: borderX, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: borderX - 10, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: borderX - 10, Y: 5, Button: tea.MouseRight})
	require.Zero(t, cfg.RunLayout().RightSidebar,
		"a right-button release must not persist the drag")

	// The drag is still live and the left release persists it once.
	r.Update(tea.MouseMotionMsg{X: borderX - 20, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: borderX - 20, Y: 5, Button: tea.MouseLeft})
	require.InDelta(t, float64(right0+20)/200.0, cfg.RunLayout().RightSidebar, 1e-9)
}

// Regression: a drag whose release never reached the view (swallowed by the
// help overlay or a view switch) stayed latched, and any later left-button
// motion resized the pane and persisted garbage.
func TestRun_MissedClickClearsStaleDragLatch(t *testing.T) {
	r, cfg := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetRightSidebarVisible(true)
	})

	_, right0 := r.TestLayoutWidths()
	borderX := 200 - right0
	// Latch a drag; the matching release is never delivered.
	r.Update(tea.MouseClickMsg{X: borderX, Y: 5, Button: tea.MouseLeft})

	// A later unrelated click-drag over the main content must not resize.
	r.Update(tea.MouseClickMsg{X: 30, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: 60, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: 60, Y: 5, Button: tea.MouseLeft})

	_, right1 := r.TestLayoutWidths()
	require.Equal(t, right0, right1, "a stale latch must not resurrect as a drag")
	require.Equal(t, leet.LayoutOverrides{}, cfg.RunLayout())
}

// Regression: live drag values were unclamped while the persisted config was
// clamped to [MinLayoutFrac, MaxLayoutFrac], so the pane snapped at the next
// relayout after release. What you drag is what persists.
func TestRun_DragExtremePersistsWhatYouSee(t *testing.T) {
	r, cfg := newTestRun(t, 300, 60, func(c *leet.ConfigManager) {
		_ = c.SetLeftSidebarVisible(true)
		_ = c.SetRightSidebarVisible(false)
	})

	left0, _ := r.TestLayoutWidths()
	r.Update(tea.MouseClickMsg{X: left0 - 1, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: 294, Y: 5, Button: tea.MouseLeft})
	liveLeft, _ := r.TestLayoutWidths()

	r.Update(tea.MouseReleaseMsg{X: 294, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.WindowSizeMsg{Width: 300, Height: 60})
	persistedLeft, _ := r.TestLayoutWidths()

	require.Equal(t, liveLeft, persistedLeft,
		"the layout must not snap when the drag is released")
	require.LessOrEqual(t, cfg.RunLayout().LeftSidebar, leet.MaxLayoutFrac)
}

// Terminals without SGR mouse support (legacy X10 encoding) report every
// release as MouseNone; such a release must still end and persist the drag.
func TestRun_LegacyMouseReleaseEndsDrag(t *testing.T) {
	r, cfg := newTestRun(t, 200, 60, func(c *leet.ConfigManager) {
		_ = c.SetRightSidebarVisible(true)
	})

	_, right0 := r.TestLayoutWidths()
	borderX := 200 - right0
	r.Update(tea.MouseClickMsg{X: borderX, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseMotionMsg{X: borderX - 10, Y: 5, Button: tea.MouseLeft})
	r.Update(tea.MouseReleaseMsg{X: borderX - 10, Y: 5, Button: tea.MouseNone})

	require.InDelta(t, float64(right0+10)/200.0, cfg.RunLayout().RightSidebar, 1e-9,
		"an X10-encoded release must persist the drag")
}
