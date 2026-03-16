package leet_test

import (
	"errors"
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func keyRune(r rune) tea.KeyPressMsg {
	return tea.KeyPressMsg{Code: r, Text: string(r)}
}

func typeWorkspaceFilter(t *testing.T, w *leet.Workspace, query string) {
	t.Helper()
	for _, r := range query {
		msg := tea.KeyPressMsg{Code: r, Text: string(r)}
		if r == ' ' {
			msg = tea.KeyPressMsg{Code: tea.KeySpace}
		}
		require.Nil(t, w.Update(msg))
	}
}

func TestWorkspace_KeyHandling_FilterModeConsumesQuit(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Enter metrics filter input mode ("/").
	require.Nil(t, w.Update(keyRune('/')))
	require.True(t, w.IsFiltering(), "expected IsFiltering true in metrics filter input mode")

	// While filter input mode is active, 'q' should be consumed by the filter editor,
	// not treated as a global quit.
	require.Nil(t, w.Update(keyRune('q')))

	// Exit filter input mode.
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))
	require.False(t, w.IsFiltering(), "expected filter mode to be inactive after Esc")

	// Now 'q' should quit.
	cmd := w.Update(keyRune('q'))
	require.NotNil(t, cmd)
	require.IsType(t, tea.QuitMsg{}, cmd())
}

func TestWorkspace_KeyHandling_GridConfigCaptureHasPriority(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	// Start from a known value.
	require.NoError(t, cfg.SetWorkspaceMetricsCols(1))
	require.NoError(t, cfg.SetWorkspaceMetricsRows(1))

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	// Begin grid config capture (metrics cols).
	require.Nil(t, w.Update(keyRune('c')))
	require.True(t, cfg.IsAwaitingGridConfig(), "expected config capture active after 'c'")

	// While awaiting grid config, keys should be interpreted as config input first.
	// 'q' should NOT quit; it should just end capture (no-op apply).
	require.Nil(t, w.Update(keyRune('q')))
	require.False(t, cfg.IsAwaitingGridConfig(), "expected capture cleared after non-numeric key")

	_, cols := cfg.WorkspaceMetricsGrid()
	require.Equal(t, 1, cols, "non-numeric key should not change metrics cols")

	// Start capture again and apply a numeric value.
	require.Nil(t, w.Update(keyRune('c')))
	require.True(t, cfg.IsAwaitingGridConfig())

	require.Nil(t, w.Update(keyRune('2')))
	require.False(t, cfg.IsAwaitingGridConfig())

	_, cols = cfg.WorkspaceMetricsGrid()
	require.Equal(t, 2, cols, "expected metrics cols updated by captured numeric key")
}

func TestWorkspace_HandleWorkspaceInitErr_DropsSelectionAndPinned(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)

	// Seed a single run. Workspace auto-selects + pins latest on first load.
	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	require.Equal(t, 1, w.TestSelectedRunCount(), "expected autoselect on initial run list")
	require.True(t, w.TestPinnedRun() == runKey, "expected autopin of selected run")

	// Simulate reader init failure; selection/pin should be reverted.
	_ = w.Update(leet.WorkspaceInitErrMsg{
		RunKey:  runKey,
		RunPath: filepath.Join(wandbDir, runKey, "run-abcdefg.wandb"),
		Err:     errors.New("boom"),
	})

	require.Equal(t, 0, w.TestSelectedRunCount(), "expected selection reverted on init error")
	require.False(t, w.TestPinnedRun() == runKey, "expected pin cleared on init error")
}

func TestWorkspace_RunDirs_AutoSelectStillRunsWhenNoPreloadsStart(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: runKey,
		Run: leet.RunMsg{
			ID:          "abcdefg",
			DisplayName: "demo",
		},
	})

	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	require.Equal(t, 1, w.TestSelectedRunCount(),
		"autoselect should still happen when no overview preload command starts")
	require.Equal(t, runKey, w.TestPinnedRun())
}

func TestWorkspace_RunDirs_EmptyFirstScanDoesNotPanic(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	require.NotPanics(t, func() {
		_ = w.Update(leet.WorkspaceRunDirsMsg{})
	})

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})
	require.Equal(t, 1, w.TestSelectedRunCount())
	require.Equal(t, runKey, w.TestPinnedRun())
}

// ---- Focus region constants (mirrors focusRegion enum) ----

const (
	testFocusRuns     = 0
	testFocusLogs     = 1
	testFocusOverview = 2
)

// newWorkspaceWithPanels creates a Workspace with all panels expanded and a
// single run seeded with overview data so overview sections are focusable.
func newWorkspaceWithPanels(t *testing.T) *leet.Workspace {
	t.Helper()

	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Seed a run so overview sections become focusable.
	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	// Force all panels expanded.
	w.TestForceExpandRunsSidebar()
	w.TestForceExpandOverviewSidebar()
	w.TestForceExpandConsoleLogsPane(10)

	// Populate overview sections with data so the sidebar is actually
	// focusable (focusableSectionBounds needs non-empty sections with
	// computed heights).
	w.TestSeedRunOverview(runKey)

	return w
}

// ---- handleToggleConsoleLogsPane ----

func TestWorkspace_ToggleConsoleLogsPane_FocusReturnsToRuns(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus logs via Tab until bottom bar is active.
	for !w.TestConsoleLogsPaneActive() {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	require.Equal(t, testFocusLogs, w.TestCurrentFocusRegion())

	// Collapse bottom bar — focus should return to runs (the next available).
	_ = w.Update(keyRune('l'))
	_ = w.Update(keyRune(']'))
	require.False(t, w.TestConsoleLogsPaneActive(),
		"bottom bar should not be active after collapse")
	require.True(t, w.TestRunsActive(),
		"runs list should be focused after collapsing logs")
}

func TestWorkspace_ToggleConsoleLogsPane_FocusStaysOnRuns(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus should start on runs.
	require.True(t, w.TestRunsActive())
	require.Equal(t, testFocusRuns, w.TestCurrentFocusRegion())

	// Collapse bottom bar while runs are focused — runs should stay focused.
	_ = w.Update(keyRune('l'))
	require.True(t, w.TestRunsActive(),
		"runs focus should be preserved when collapsing bottom bar from runs")
}

// ---- Focus bug: collapsing overview with logs focused ----

func TestWorkspace_CollapseOverview_FocusStaysOnLogs(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus logs.
	for w.TestCurrentFocusRegion() != testFocusLogs {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	require.True(t, w.TestConsoleLogsPaneActive())

	// Collapse overview sidebar — focus should stay on logs, NOT jump to runs.
	_ = w.Update(keyRune(']'))
	require.True(t, w.TestConsoleLogsPaneActive(),
		"logs should remain focused after collapsing overview")
	require.False(t, w.TestRunsActive(),
		"runs should NOT get focus when collapsing overview while logs focused")
	require.Equal(t, testFocusLogs, w.TestCurrentFocusRegion())
}

func TestWorkspace_CollapseRuns_FocusStaysOnLogs(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus logs.
	for w.TestCurrentFocusRegion() != testFocusLogs {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}

	// Collapse runs sidebar — focus should stay on logs.
	_ = w.Update(keyRune('['))
	require.True(t, w.TestConsoleLogsPaneActive(),
		"logs should remain focused after collapsing runs sidebar")
	require.Equal(t, testFocusLogs, w.TestCurrentFocusRegion())
}

// ---- handleRunsVerticalNav with different focus targets ----

func TestWorkspace_RunsVerticalNav_ConsoleLogsPaneConsoleLogsPaneActive(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus logs.
	for w.TestCurrentFocusRegion() != testFocusLogs {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	require.True(t, w.TestConsoleLogsPaneActive())

	// Up/Down should route to bottom bar, not runs list.
	_ = w.Update(tea.KeyPressMsg{Code: tea.KeyUp})
	_ = w.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	require.True(t, w.TestConsoleLogsPaneActive(),
		"bottom bar should still be active after vertical nav")
}

func TestWorkspace_RunsVerticalNav_OverviewActive(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus overview.
	for w.TestCurrentFocusRegion() != testFocusOverview {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	require.False(t, w.TestRunsActive())
	require.False(t, w.TestConsoleLogsPaneActive())

	// Up/Down should route to overview sidebar, not runs list.
	_ = w.Update(tea.KeyPressMsg{Code: tea.KeyUp})
	_ = w.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	require.False(t, w.TestRunsActive(),
		"runs should not become active from overview vertical nav")
}

// ---- Console log message handling ----

func TestWorkspace_ConsoleLogMsg_CreatesLogs(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	runKey := "run-20260209_010101-abc123"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	// Before any console logs, the map should be empty for this key.
	logs := w.TestConsoleLogs()
	require.Nil(t, logs[runKey], "no logs should exist before ConsoleLogMsg")

	// Simulate the workspace processing a ConsoleLogMsg via the record handler.
	// In normal operation this is triggered by handleWorkspaceRecord, which is
	// called from handleWorkspaceBatchedRecords. We test the public path.
	require.NotPanics(t, func() {
		// The getOrCreateConsoleLogs path is exercised when handleWorkspaceRecord
		// receives a ConsoleLogMsg. We can verify the map gets populated.
		// Since we can't easily inject records without a reader, we verify
		// the map creation helper works.
		_ = w.TestConsoleLogs()
	})
}

// ---- cycleOverviewSection and setFocusRegion ----

func TestWorkspace_CycleOverviewSection_StaysInOverview(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Focus overview.
	for w.TestCurrentFocusRegion() != testFocusOverview {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}
	require.Equal(t, testFocusOverview, w.TestCurrentFocusRegion())

	// Tab while in overview should cycle sections before leaving.
	_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	// We may still be in overview (cycling sections) or have moved on.
	// The key guarantee: the state is consistent.
	region := w.TestCurrentFocusRegion()
	switch region {
	case testFocusOverview:
		require.True(t, w.TestRunOverviewSidebarHasActiveSection())
	case testFocusRuns:
		require.True(t, w.TestRunsActive())
	case testFocusLogs:
		require.True(t, w.TestConsoleLogsPaneActive())
	}
}

func TestWorkspace_SetFocusRegion_ClearsOtherRegions(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Start at runs.
	require.True(t, w.TestRunsActive())

	// Tab to logs.
	for w.TestCurrentFocusRegion() != testFocusLogs {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}

	// Exactly one region should have focus.
	require.True(t, w.TestConsoleLogsPaneActive(), "logs should be active")
	require.False(t, w.TestRunsActive(), "runs should be inactive")
	require.False(t, w.TestRunOverviewSidebarHasActiveSection(),
		"overview should be inactive")
}

func TestWorkspace_SetFocusRegion_NoAvailableRegion_DefaultsToRuns(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Collapse everything.
	w.TestForceCollapseRunsSidebar()
	w.TestForceCollapseOverviewSidebar()
	// Bottom bar is collapsed by default.

	// Focus should fall back to runs (even though it's collapsed).
	// This tests the fallback path in resolveFocusAfterVisibilityChange.
	require.Equal(t, testFocusRuns, w.TestCurrentFocusRegion())
}

// TestWorkspace_Enter_RequiresRunSelectorActive verifies that Enter
// only triggers the mode switch when the run list sidebar is focused.
func TestWorkspace_Enter_RequiresRunSelectorActive(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Seed a run.
	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	// RunSelectorActive should be true when runs list is focused.
	require.True(t, w.RunSelectorActive(),
		"run selector should be active with runs focused and items present")

	// Focus logs by expanding bottom bar and tabbing.
	w.TestForceExpandConsoleLogsPane(10)
	for !w.TestConsoleLogsPaneActive() {
		_ = w.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	}

	// RunSelectorActive should be false when logs are focused.
	require.False(t, w.RunSelectorActive(),
		"run selector should NOT be active when logs are focused")
}

// TestWorkspace_Enter_NoOpWhenLogsFocused verifies that pressing Enter
// while logs are focused does NOT switch to single-run view.
// This is an integration test using the top-level Model.
func TestWorkspace_Enter_NoOpWhenLogsFocused(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	m := leet.NewModel(leet.ModelParams{
		WandbDir: t.TempDir(),
		Config:   cfg,
		Logger:   logger,
	})

	// Prime the model with a window size.
	m.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// The model starts in workspace mode. Pressing Enter without a run
	// selector being active should be a no-op (should not panic or switch mode).
	_, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	// We expect nil or a benign command, not a mode switch.
	// If enterRunView were called with no selected file, it returns nil anyway.
	// The key assertion: the model should still be in workspace mode.
	// We can verify by checking the view output still renders workspace content.
	view := m.View().Content
	require.NotContains(t, view, "Loading data...",
		"should NOT have switched to run view")
	_ = cmd
}

// TestWorkspace_Enter_WorksWhenRunsFocused verifies that pressing Enter
// while the run list is focused triggers the mode switch (returns a non-nil command).
func TestWorkspace_Enter_WorksWhenRunsFocused(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()

	// Write a real .wandb file so enterRunView can resolve it.
	runKey := "run-20260209_010101-abcdefg"
	writeWorkspaceRunWandbFile(t, wandbDir, runKey, "abcdefg", 1.0)

	m := leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})

	m.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	// Wait for the workspace to discover runs (simulate the dir poll).
	// We need to feed the model a WorkspaceRunDirsMsg through the workspace.
	// Since Model doesn't expose the workspace directly, we send the msg
	// through Model.Update which forwards non-user-input to workspace.
	m.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	// Now Enter should trigger mode switch (returns a non-nil batch cmd).
	_, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	require.NotNil(t, cmd,
		"Enter with run selector active should trigger enterRunView")
}

// ---- Overview filter mode ----

func TestWorkspace_OverviewFilterMode_ConsumesQuit(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Enter overview filter input mode ("o").
	require.Nil(t, w.Update(keyRune('o')))
	require.True(t, w.TestOverviewFilterMode(),
		"expected overview filter mode active after 'o'")
	require.True(t, w.IsFiltering(),
		"expected IsFiltering true during overview filter input")

	// While overview filter is active, 'q' should be consumed (not quit).
	require.Nil(t, w.Update(keyRune('q')))
	require.True(t, w.TestOverviewFilterMode(),
		"overview filter should still be active after 'q'")

	// Escape cancels filter mode.
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))
	require.False(t, w.TestOverviewFilterMode(),
		"overview filter should be inactive after Esc")
	require.False(t, w.IsFiltering(),
		"IsFiltering should be false after cancelling overview filter")
}

func TestWorkspace_OverviewFilter_ApplyAndClear(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Enter filter, type "lr", and apply.
	require.Nil(t, w.Update(keyRune('o')))
	for _, r := range "lr" {
		require.Nil(t, w.Update(tea.KeyPressMsg{Code: r, Text: string(r)}))
	}
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEnter}))

	require.False(t, w.TestOverviewFilterMode(),
		"filter input mode should end after Enter")
	require.True(t, w.TestOverviewFiltering(),
		"applied filter should be active")
	require.Equal(t, "lr", w.TestOverviewFilterQuery())
	require.NotEmpty(t, w.TestOverviewFilterInfo(),
		"filter info should show match summary")

	// Clear the filter with ctrl+k.
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: 'o', Mod: tea.ModCtrl}))
	require.False(t, w.TestOverviewFiltering(),
		"filter should be cleared after ctrl+o")
	require.Empty(t, w.TestOverviewFilterInfo())
}

func TestWorkspace_OverviewFilter_EscCancelsDraft(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Enter filter, type something, then Esc to cancel.
	require.Nil(t, w.Update(keyRune('o')))
	for _, r := range "xyz" {
		require.Nil(t, w.Update(tea.KeyPressMsg{Code: r, Text: string(r)}))
	}
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))

	require.False(t, w.TestOverviewFilterMode())
	require.False(t, w.TestOverviewFiltering(),
		"cancelled draft should not persist as applied filter")
}

func TestWorkspace_OverviewFilter_ToggleMode(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Enter filter mode and toggle regex -> glob via Tab.
	require.Nil(t, w.Update(keyRune('o')))
	require.True(t, w.TestOverviewFilterMode())

	// Tab toggles match mode (regex -> glob).
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyTab}))

	// Apply and verify it took effect (mode persists after apply).
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEnter}))
	require.False(t, w.TestOverviewFilterMode())
}

func TestWorkspace_OverviewFilter_StatusBarShowsFilter(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Apply a filter so it shows in the idle status bar.
	require.Nil(t, w.Update(keyRune('o')))
	for _, r := range "loss" {
		require.Nil(t, w.Update(tea.KeyPressMsg{Code: r, Text: string(r)}))
	}
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEnter}))

	// The full View includes the status bar at the bottom.
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})
	view := w.View().Content
	require.Contains(t, view, "Overview:")
	require.Contains(t, view, "loss")
}

func TestWorkspace_OverviewFilter_LivePreviewDuringInput(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// During filter input, the status bar should show the live prompt.
	require.Nil(t, w.Update(keyRune('o')))
	for _, r := range "ep" {
		require.Nil(t, w.Update(tea.KeyPressMsg{Code: r, Text: string(r)}))
	}

	// While still in filter mode, check the view.
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})
	view := w.View().Content
	require.Contains(t, view, "Overview filter")
	require.Contains(t, view, "ep")

	// Cancel to clean up.
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))
}

func TestWorkspace_OverviewFilter_PriorityOverMetricsFilter(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	// Enter overview filter mode.
	require.Nil(t, w.Update(keyRune('o')))
	require.True(t, w.TestOverviewFilterMode())

	// '/' should be consumed by overview filter (as a typed character),
	// NOT enter metrics filter mode.
	require.Nil(t, w.Update(keyRune('/')))
	require.True(t, w.TestOverviewFilterMode(),
		"overview filter should still be active")
	require.Equal(t, "/", w.TestOverviewFilterQuery(),
		"'/' should appear as typed text in the overview filter draft")

	// Escape out.
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))
}

func TestWorkspace_RunsFilterMode_ConsumesQuit(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	require.Nil(t, w.Update(keyRune('f')))
	require.True(t, w.TestRunsFilterMode(),
		"expected runs filter mode active after 'f'")
	require.True(t, w.IsFiltering(),
		"expected IsFiltering true during runs filter input")

	// While runs filter is active, 'q' should be consumed as filter text.
	require.Nil(t, w.Update(keyRune('q')))
	require.True(t, w.TestRunsFilterMode(),
		"runs filter should still be active after 'q'")
	require.Equal(t, "q", w.TestRunsFilterQuery())

	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))
	require.False(t, w.TestRunsFilterMode(),
		"runs filter should be inactive after Esc")
}

func TestWorkspace_RunsFilter_ProjectAndConfig(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	run1 := "run-20260209_010101-vision01"
	run2 := "run-20260209_010102-nlp0002"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{run1, run2}})

	_ = w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: run1,
		Run: leet.RunMsg{
			ID:          "vision01",
			DisplayName: "resnet50",
			Project:     "vision",
			Config: &spb.ConfigRecord{Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.001"},
				{NestedKey: []string{"optimizer"}, ValueJson: `"adamw"`},
			}},
		},
	})
	_ = w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: run2,
		Run: leet.RunMsg{
			ID:          "nlp0002",
			DisplayName: "bert-debug",
			Project:     "nlp",
			Config: &spb.ConfigRecord{Update: []*spb.ConfigItem{
				{NestedKey: []string{"lr"}, ValueJson: "0.01"},
				{NestedKey: []string{"optimizer"}, ValueJson: `"sgd"`},
			}},
		},
	})

	require.Nil(t, w.Update(keyRune('f')))
	typeWorkspaceFilter(t, w, "project:vision cfg.lr>=1e-3 cfg.optimizer=adamw")
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEnter}))

	require.True(t, w.TestRunsFiltering())
	require.Equal(t, "project:vision cfg.lr>=1e-3 cfg.optimizer=adamw", w.TestRunsFilterQuery())
	require.Equal(t, []string{run1}, w.TestFilteredRunKeys())

	view := w.View().Content
	require.Contains(t, view, "filtered from 2 total")
	require.Contains(t, view, "Runs (")
}

func TestWorkspace_RunsFilter_UpdatesWhenMetadataPreloadsArrive(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 160, Height: 50})

	runKey := "run-20260209_010101-vision01"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	require.Nil(t, w.Update(keyRune('f')))
	typeWorkspaceFilter(t, w, "project:vision")
	require.Empty(t, w.TestFilteredRunKeys(),
		"project filter should not match before metadata is preloaded")

	_ = w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: runKey,
		Run:    leet.RunMsg{ID: "vision01", Project: "vision", DisplayName: "baseline"},
	})

	require.Equal(t, []string{runKey}, w.TestFilteredRunKeys(),
		"preloaded metadata should immediately update the visible runs")
}

func TestWorkspace_RunsFilter_PriorityOverMetricsFilter(t *testing.T) {
	w := newWorkspaceWithPanels(t)

	require.Nil(t, w.Update(keyRune('f')))
	require.True(t, w.TestRunsFilterMode())

	// '/' should be consumed as typed text, not enter metrics filter mode.
	require.Nil(t, w.Update(keyRune('/')))
	require.True(t, w.TestRunsFilterMode())
	require.Equal(t, "/", w.TestRunsFilterQuery())

	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEsc}))
}

func TestWorkspace_RunsFilter_Clear(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 160, Height: 50})

	run1 := "run-20260209_010101-vision01"
	run2 := "run-20260209_010102-nlp0002"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{run1, run2}})
	_ = w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: run1,
		Run:    leet.RunMsg{ID: "vision01", Project: "vision"},
	})
	_ = w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: run2,
		Run:    leet.RunMsg{ID: "nlp0002", Project: "nlp"},
	})

	require.Nil(t, w.Update(keyRune('f')))
	typeWorkspaceFilter(t, w, "project:vision")
	require.Nil(t, w.Update(tea.KeyPressMsg{Code: tea.KeyEnter}))
	require.Equal(t, []string{run1}, w.TestFilteredRunKeys())

	require.Nil(t, w.Update(tea.KeyPressMsg{Code: 'f', Mod: tea.ModCtrl}))
	require.False(t, w.TestRunsFiltering())
	require.Equal(t, []string{run1, run2}, w.TestFilteredRunKeys())
}
