package leet_test

import (
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
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
		r.Update(tea.KeyMsg{Type: tea.KeyTab})
	}
	require.Equal(t, lastSec, r.TestLeftSidebarActiveSectionIdx(),
		"should have reached last overview section")

	// One more Tab → logs.
	r.Update(tea.KeyMsg{Type: tea.KeyTab})
	require.True(t, r.TestConsoleLogsPaneActive(), "Tab past last section should focus logs")
	require.False(t, r.TestLeftSidebarHasActiveSection(),
		"overview sections should be deactivated when logs focused")

	// Tab from logs → overview first section.
	r.Update(tea.KeyMsg{Type: tea.KeyTab})
	require.False(t, r.TestConsoleLogsPaneActive(), "Tab from logs should leave logs")
	require.True(t, r.TestLeftSidebarHasActiveSection(), "should re-enter overview")
}

func TestRun_SidebarTabNav_OnlyLogsVisible(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)
	r.TestForceCollapseLeftSidebar()

	// With overview collapsed, Tab should activate logs.
	r.Update(tea.KeyMsg{Type: tea.KeyTab})
	require.True(t, r.TestConsoleLogsPaneActive(),
		"Tab with collapsed overview should still reach logs")
}

func TestRun_SidebarTabNav_OnlyOverviewVisible(t *testing.T) {
	r := newRunForHandlerTest(t)
	// Bottom bar collapsed (default).
	require.False(t, r.TestConsoleLogsPaneExpanded(), "bottom bar should start collapsed")

	// Tab should cycle through overview sections without reaching logs.
	initialSection := r.TestLeftSidebarActiveSectionIdx()
	r.Update(tea.KeyMsg{Type: tea.KeyTab})
	nextSection := r.TestLeftSidebarActiveSectionIdx()
	require.NotEqual(t, initialSection, nextSection,
		"Tab should cycle overview sections")
	require.False(t, r.TestConsoleLogsPaneActive(),
		"logs should never get focus when collapsed")
}

// ---- handleSidebarVerticalNav ----

func TestRun_SidebarVerticalNav_LogsFocused(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)

	// Focus logs and add some data.
	r.Update(tea.KeyMsg{Type: tea.KeyTab})
	for !r.TestConsoleLogsPaneActive() {
		r.Update(tea.KeyMsg{Type: tea.KeyTab})
	}

	// Vertical nav should not panic even without log data.
	r.Update(tea.KeyMsg{Type: tea.KeyUp})
	r.Update(tea.KeyMsg{Type: tea.KeyDown})
}

func TestRun_SidebarVerticalNav_OverviewFocused(t *testing.T) {
	r := newRunForHandlerTest(t)

	// Sidebar should be focused with sections.
	require.True(t, r.TestLeftSidebarHasActiveSection())

	sidebar := r.TestGetLeftSidebar()
	k1, _ := sidebar.SelectedItem()
	require.NotEmpty(t, k1, "should have a selected item")

	r.Update(tea.KeyMsg{Type: tea.KeyDown})
	k2, _ := sidebar.SelectedItem()
	// The selected item may or may not change (depends on section content),
	// but it should not panic and should remain valid.
	require.NotEmpty(t, k2)
}

func TestRun_SidebarVerticalNav_SidebarCollapsed(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceCollapseLeftSidebar()

	// With sidebar collapsed, vertical nav should be a no-op.
	r.Update(tea.KeyMsg{Type: tea.KeyUp})
	r.Update(tea.KeyMsg{Type: tea.KeyDown})
}

// ---- handleSidebarPageNav ----

func TestRun_SidebarPageNav_LogsFocused(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceExpandConsoleLogsPane(10)

	// Focus logs.
	r.Update(tea.KeyMsg{Type: tea.KeyTab})
	for !r.TestConsoleLogsPaneActive() {
		r.Update(tea.KeyMsg{Type: tea.KeyTab})
	}

	// Left/Right should page through logs (no-op with empty logs, but shouldn't panic).
	r.Update(tea.KeyMsg{Type: tea.KeyLeft})
	r.Update(tea.KeyMsg{Type: tea.KeyRight})
}

func TestRun_SidebarPageNav_OverviewFocused(t *testing.T) {
	r := newRunForHandlerTest(t)
	require.True(t, r.TestLeftSidebarHasActiveSection())

	// Left/Right should page through overview sections.
	r.Update(tea.KeyMsg{Type: tea.KeyLeft})
	r.Update(tea.KeyMsg{Type: tea.KeyRight})
}

func TestRun_SidebarPageNav_SidebarCollapsed(t *testing.T) {
	r := newRunForHandlerTest(t)
	r.TestForceCollapseLeftSidebar()

	// With sidebar collapsed, page nav should be a no-op.
	r.Update(tea.KeyMsg{Type: tea.KeyLeft})
	r.Update(tea.KeyMsg{Type: tea.KeyRight})
}
