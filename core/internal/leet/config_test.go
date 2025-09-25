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
	// Not parallel: touches global config & exported grid vars.
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	err := cfg.Load()
	require.NoError(t, err)

	var m tea.Model = leet.NewModel("dummy", observability.NewNoOpLogger())
	// Ensure model is sized so internal recomputations run.
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// metrics rows: 'r' then '5'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'5'}})
	gridRows, _ := cfg.GetMetricsGrid()
	require.Equal(t, gridRows, 5)

	// metrics cols: 'c' then '4'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'c'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'4'}})
	_, gridCols := cfg.GetMetricsGrid()
	require.Equal(t, gridCols, 4)

	// system rows: 'R' then '2'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'R'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'2'}})
	gridRows, _ = cfg.GetSystemGrid()
	require.Equal(t, gridRows, 2)

	// system cols: 'C' then '3'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'C'}})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'3'}})
	_, gridCols = cfg.GetSystemGrid()
	require.Equal(t, gridCols, 3)
}

func TestConfig_SetLeftSidebarVisible_TogglesAndPersists(t *testing.T) {
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	err := cfg.Load()
	require.NoError(t, err)

	// Toggle on
	err = cfg.SetLeftSidebarVisible(true)
	require.NoError(t, err)
	require.True(t, cfg.GetLeftSidebarVisible())

	// Toggle off
	err = cfg.SetLeftSidebarVisible(false)
	require.NoError(t, err)
	require.False(t, cfg.GetLeftSidebarVisible())
}

func TestConfig_SetLeftSidebarVisible_AffectsModelOnStartup(t *testing.T) {
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	err := cfg.Load()
	require.NoError(t, err)

	err = cfg.SetLeftSidebarVisible(true)
	require.NoError(t, err)

	m := leet.NewModel("dummy", observability.NewNoOpLogger())
	var tm tea.Model = m
	tm, _ = tm.Update(tea.WindowSizeMsg{Width: 160, Height: 60})

	model := tm.(*leet.Model)
	require.True(t, model.TestLeftSidebarVisible())
}
