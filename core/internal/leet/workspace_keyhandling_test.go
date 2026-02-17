package leet_test

import (
	"errors"
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func keyRune(r rune) tea.KeyMsg {
	return tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}}
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
	require.Nil(t, w.Update(tea.KeyMsg{Type: tea.KeyEsc}))
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
	require.NoError(t, cfg.SetMetricsCols(1))
	require.NoError(t, cfg.SetMetricsRows(1))

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	// Begin grid config capture (metrics cols).
	require.Nil(t, w.Update(keyRune('c')))
	require.True(t, cfg.IsAwaitingGridConfig(), "expected config capture active after 'c'")

	// While awaiting grid config, keys should be interpreted as config input first.
	// 'q' should NOT quit; it should just end capture (no-op apply).
	require.Nil(t, w.Update(keyRune('q')))
	require.False(t, cfg.IsAwaitingGridConfig(), "expected capture cleared after non-numeric key")

	_, cols := cfg.MetricsGrid()
	require.Equal(t, 1, cols, "non-numeric key should not change metrics cols")

	// Start capture again and apply a numeric value.
	require.Nil(t, w.Update(keyRune('c')))
	require.True(t, cfg.IsAwaitingGridConfig())

	require.Nil(t, w.Update(keyRune('2')))
	require.False(t, cfg.IsAwaitingGridConfig())

	_, cols = cfg.MetricsGrid()
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
