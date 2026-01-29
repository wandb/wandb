package leet_test

import (
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewRun("dummy", cfg, logger)
	// Ensure model is sized so internal recomputations run.
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// metrics rows: 'r' then '5'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'5'}})
	gridRows, _ := cfg.MetricsGrid()
	require.Equal(t, gridRows, 5)

	// metrics cols: 'c' then '4'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'c'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'4'}})
	_, gridCols := cfg.MetricsGrid()
	require.Equal(t, gridCols, 4)

	// system rows: 'R' then '2'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'R'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'2'}})
	gridRows, _ = cfg.SystemGrid()
	require.Equal(t, gridRows, 2)

	// system cols: 'C' then '3'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'C'}})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'3'}})
	_, gridCols = cfg.SystemGrid()
	require.Equal(t, gridCols, 3)
}

func TestConfig_SetLeftSidebarVisible_TogglesAndPersists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	// Toggle on
	err := cfg.SetLeftSidebarVisible(true)
	require.NoError(t, err)
	require.True(t, cfg.LeftSidebarVisible())

	// Toggle off
	err = cfg.SetLeftSidebarVisible(false)
	require.NoError(t, err)
	require.False(t, cfg.LeftSidebarVisible())
}

func TestConfig_SetLeftSidebarVisible_AffectsModelOnStartup(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	err := cfg.SetLeftSidebarVisible(true)
	require.NoError(t, err)

	m := leet.NewRun("dummy", cfg, logger)
	var tm tea.Model = m
	tm, _ = tm.Update(tea.WindowSizeMsg{Width: 160, Height: 60})

	model := tm.(*leet.Run)
	require.True(t, model.TestLeftSidebarVisible())
}
