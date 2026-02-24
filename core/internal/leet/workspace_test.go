package leet_test

import (
	"os"
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestModel_WorkspaceFilterDoesNotLeakIntoRunView(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	runDir := "run-20250731_170606-iazb7i1k"
	runFile := filepath.Join(wandbDir, runDir, "run-iazb7i1k.wandb")
	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))
	require.NoError(t, os.WriteFile(runFile, nil, 0o644))

	var model tea.Model = leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})

	// Seed workspace run list.
	model, _ = model.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runDir}})
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Workspace: set metrics filter to "train".
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	for _, r := range "train" {
		model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
	}
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter}) // apply

	// Enter run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Run view: apply metrics filter "x".
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'x'}})
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Exit run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEsc})

	// Workspace filter must remain "train" (not "trainx").
	view := stripANSI(model.View())
	require.Contains(t, view, `"train"`)
	require.NotContains(t, view, `"trainx"`)
}

func TestModel_CtrlLInRunViewDoesNotClearWorkspaceFilter(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	runDir := "run-20250731_170606-iazb7i1k"
	runFile := filepath.Join(wandbDir, runDir, "run-iazb7i1k.wandb")
	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))
	require.NoError(t, os.WriteFile(runFile, nil, 0o644))

	var model tea.Model = leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})

	model, _ = model.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runDir}})
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Workspace: set filter to "train".
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	for _, r := range "train" {
		model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
	}
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Enter run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Clear filter in run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyCtrlL})

	// Exit run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEsc})

	view := stripANSI(model.View())
	require.Contains(t, view, `"train"`)
}

func TestWorkspace_View_SystemMetricsPaneShowsRunLabel(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	w.TestForceExpandSystemMetricsPane(20)
	require.True(t, w.TestSystemMetricsPane().IsVisible())

	view := stripANSI(w.View())
	require.Contains(t, view, leet.WorkspaceSystemMetricsPaneHeader)
	require.Contains(t, view, runKey,
		"system metrics pane header should include the current run label")
}

func TestWorkspace_View_SystemMetricsPaneShowsSelectHint(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	// Deselect the run if auto-selected.
	if w.TestIsRunSelected(runKey) {
		_ = w.Update(tea.KeyMsg{Type: tea.KeySpace})
	}
	require.False(t, w.TestIsRunSelected(runKey))

	w.TestForceExpandSystemMetricsPane(20)

	view := stripANSI(w.View())
	require.Contains(t, view, "Select this run (Space) to load system metrics.",
		"unselected run should show select hint in system metrics pane")
}

func TestWorkspace_View_BottomBarRendersWhenVisible(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	w.TestForceExpandBottomBar(10)
	require.True(t, w.TestBottomBarExpanded())

	view := stripANSI(w.View())
	require.Contains(t, view, "Console Logs",
		"workspace view should include Console Logs header when bottom bar is visible")
}

func TestWorkspace_View_BottomBarShowsNoDataWithoutLogs(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	w.TestForceExpandBottomBar(10)

	view := stripANSI(w.View())
	require.Contains(t, view, "No data.",
		"bottom bar should show 'No data.' when no console logs exist")
}

func TestWorkspace_View_HiddenPanesNotRendered(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 60})

	require.False(t, w.TestSystemMetricsPane().IsVisible())
	require.False(t, w.TestBottomBarExpanded())

	view := stripANSI(w.View())
	require.NotContains(t, view, "Console Logs",
		"collapsed bottom bar should not appear in view")
}

func TestWorkspace_View_BothPanesVisibleSimultaneously(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 200, Height: 80})

	runKey := "run-20260209_010101-abcdefg"
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runKey}})

	w.TestForceExpandSystemMetricsPane(15)
	w.TestForceExpandBottomBar(10)

	view := stripANSI(w.View())
	require.Contains(t, view, leet.WorkspaceSystemMetricsPaneHeader,
		"system metrics pane should be in view")
	require.Contains(t, view, "Console Logs",
		"console logs should be in view")
	require.Contains(t, view, runKey,
		"run label should appear in view")
}
