package leet_test

import (
	"path/filepath"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func selectField(t *testing.T, m tea.Model, jsonKey string) tea.Model {
	t.Helper()

	needle := "(" + jsonKey + ")"
	for range 50 {
		if strings.Contains(m.View(), needle) {
			return m
		}
		m, _ = m.Update(tea.KeyMsg{Type: tea.KeyDown})
	}
	require.Failf(t, "field not found", "expected %q in view output", needle)
	return m
}

func TestConfigEditor_EnumChange_SaveAndPersists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "startup_mode")

	// Enter opens enum selection; Down selects single_run_latest.
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyDown})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Save & quit.
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'s'}})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)

	// Reload from disk to verify persistence.
	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, leet.StartupModeSingleRunLatest, cfg2.Snapshot().StartupMode)
}

func TestConfigEditor_QuitConfirmation_RespectsCtrlCAndClearsOnOtherKeys(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "startup_mode")

	// Make the model dirty (cycle the startup mode enum).
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRight})

	// First Ctrl+C should prompt (no quit).
	m, cmd := m.Update(tea.KeyMsg{Type: tea.KeyCtrlC})
	require.Nil(t, cmd)
	require.Contains(t, m.View(), "Unsaved changes")

	// Any other key clears the confirmation prompt.
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyDown})
	require.NotContains(t, m.View(), "Unsaved changes")

	// Ctrl+C again: prompt again.
	m, cmd = m.Update(tea.KeyMsg{Type: tea.KeyCtrlC})
	require.Nil(t, cmd)

	// Ctrl+C again: now quit.
	_, cmd = m.Update(tea.KeyMsg{Type: tea.KeyCtrlC})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)
}

func TestConfigEditor_CtrlCQuitsFromEnumModal_WhenClean(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "startup_mode")

	// Enter enum modal, then Ctrl+C should quit immediately (no unsaved changes).
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyCtrlC})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)
}

func TestConfigEditor_IntEdit_ValidatesAndApplies(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "heartbeat_interval_seconds")

	// Enter int edit mode.
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Clear current input (default 15) and enter an invalid value 0.
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'0'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})
	require.Contains(t, m.View(), "Must be >= 1")

	// Replace with valid value 10.
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("10")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})
	require.NotContains(t, m.View(), "Must be >= 1")

	// Save & quit.
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'s'}})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)

	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, 10, cfg2.Snapshot().HeartbeatInterval)
}

func TestConfigEditor_DefaultDescriptionsForGridConfig(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "metrics_grid.rows")

	view := m.View()
	require.Contains(t, view, "Rows in the main metrics grid.")
	require.Contains(t, view, "(metrics_grid.rows)")
}
