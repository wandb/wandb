package leet_test

import (
	"path/filepath"
	"testing"

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

	r := leet.NewRun("testdata/fake.wandb", cfg, logger)
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

// ---- handleSidebarTabNav ----

func TestRun_SidebarTabNav_BothPanelsVisible_CyclesOverviewThenLogs(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)

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
	r.TestForceCollapseLeftSidebar()

	// With overview collapsed, Tab should activate logs.
	r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.True(t, r.TestConsoleLogsPaneActive(),
		"Tab with collapsed overview should still reach logs")
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

	r := leet.NewRun("testdata/fake.wandb", cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	require.True(t, r.TestConsoleLogsPaneActive(),
		"the first available pane should receive focus on load")
	require.False(t, r.TestLeftSidebarHasActiveSection(),
		"collapsed overview should not appear focused")
}

func TestRun_OverviewUpdatesPreserveTabContext(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetLeftSidebarVisible(true)

	r := leet.NewRun("testdata/fake.wandb", cfg, logger)
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

// keyLetter builds a key press for a single rune.
func keyLetter(r rune) tea.KeyPressMsg {
	return tea.KeyPressMsg{Code: r, Text: string(r)}
}

// TestRun_UnifiedNav_WSMatchesUpDownOnOverview verifies that 'w'/'s' move
// the overview cursor the same way Up/Down do.
func TestRun_UnifiedNav_WSMatchesUpDownOnOverview(t *testing.T) {
	r := newRunForHandlerTest(t)
	require.True(t, r.TestLeftSidebarHasActiveSection(), "overview should be focused")

	sidebar := r.TestGetLeftSidebar()
	before, _ := sidebar.SelectedItem()

	r.Update(keyLetter('s'))
	afterS, _ := sidebar.SelectedItem()
	r.Update(keyLetter('w'))
	afterW, _ := sidebar.SelectedItem()

	r.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	afterDown, _ := sidebar.SelectedItem()

	require.NotEmpty(t, before)
	require.Equal(t, afterS, afterDown,
		"'s' and Down should land on the same item")
	require.Equal(t, before, afterW,
		"'w' should undo 's'")
}

// TestRun_UnifiedNav_ADMatchesLeftRightOnOverview verifies that 'a'/'d' do
// the same page nav that Left/Right do inside the overview.
func TestRun_UnifiedNav_ADMatchesLeftRightOnOverview(t *testing.T) {
	r := newRunForHandlerTest(t)
	require.True(t, r.TestLeftSidebarHasActiveSection())

	// Page nav is a no-op when there's only one page, but it must not panic
	// and must leave focus intact.
	r.Update(keyLetter('d'))
	r.Update(keyLetter('a'))
	r.Update(tea.KeyPressMsg{Code: tea.KeyRight})
	r.Update(tea.KeyPressMsg{Code: tea.KeyLeft})

	require.True(t, r.TestLeftSidebarHasActiveSection(),
		"overview should remain focused after page-nav aliases")
}

// TestRun_UnifiedNav_HomeEnd_OverviewFocused verifies Home/End in overview
// jumps between first/last items of the active section.
func TestRun_UnifiedNav_HomeEnd_OverviewFocused(t *testing.T) {
	r := newRunForHandlerTest(t)
	sidebar := r.TestGetLeftSidebar()

	// Give overview global focus so vertical nav + Home/End dispatch there.
	r.TestSetFocusTarget(int(leet.FocusTargetOverview))

	// Move cursor down at least once so Home is observable.
	r.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	afterDown, _ := sidebar.SelectedItem()

	r.Update(tea.KeyPressMsg{Code: tea.KeyHome})
	afterHome, _ := sidebar.SelectedItem()
	require.NotEqual(t, afterDown, afterHome,
		"Home should move the cursor away from the post-Down position")

	r.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
	afterEnd, _ := sidebar.SelectedItem()
	require.NotEqual(t, afterHome, afterEnd,
		"End should move the cursor away from the Home position")
}

// TestRun_UnifiedNav_HomeEnd_LogsFocused verifies that Home scrolls logs to
// the start and End to the end; both should not panic when logs are empty.
func TestRun_UnifiedNav_HomeEnd_LogsFocused(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)

	// Focus logs.
	for !r.TestConsoleLogsPaneActive() {
		r.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}

	require.NotPanics(t, func() {
		r.Update(tea.KeyPressMsg{Code: tea.KeyHome})
		r.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
	})
}

// TestRun_UnifiedNav_ArrowsInGrid_MoveChartFocus verifies that arrow keys
// move chart focus when a grid is focused (matching wasd semantics).
func TestRun_UnifiedNav_ArrowsInGrid_MoveChartFocus(t *testing.T) {
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

	// Right arrow should advance the focused column like 'd'.
	r.Update(tea.KeyPressMsg{Code: tea.KeyRight})
	require.Equal(t, 1, focus.Col,
		"Right arrow should advance chart focus one column")

	// Down arrow should advance the focused row like 's'.
	r.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	require.Equal(t, 1, focus.Row,
		"Down arrow should advance chart focus one row")
}
