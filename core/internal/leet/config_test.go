package leet_test

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	runParams := &leet.RunParams{
		LocalRunParams: &leet.LocalRunParams{
			RunFile: "dummy",
		},
	}
	run := leet.NewRun(runParams, cfg, logger)
	var m tea.Model = run
	// Ensure model is sized so internal recomputations run.
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// metrics rows: 'r' then '5' (default focus = metrics grid)
	m, _ = m.Update(tea.KeyPressMsg{Code: 'r'})
	m, _ = m.Update(tea.KeyPressMsg{Code: '5'})
	gridRows, _ := cfg.MetricsGrid()
	require.Equal(t, gridRows, 5)

	// metrics cols: 'c' then '4'
	m, _ = m.Update(tea.KeyPressMsg{Code: 'c'})
	m, _ = m.Update(tea.KeyPressMsg{Code: '4'})
	_, gridCols := cfg.MetricsGrid()
	require.Equal(t, gridCols, 4)

	// Focus system metrics, then use universal 'r'/'c' to configure system grid.
	run.TestSetFocusTarget(int(leet.FocusTargetSystemMetrics))

	// system rows: 'r' then '2'
	m, _ = m.Update(tea.KeyPressMsg{Code: 'r'})
	m, _ = m.Update(tea.KeyPressMsg{Code: '2'})
	gridRows, _ = cfg.SystemGrid()
	require.Equal(t, gridRows, 2)

	// system cols: 'c' then '3'
	m, _ = m.Update(tea.KeyPressMsg{Code: 'c'})
	_, _ = m.Update(tea.KeyPressMsg{Code: '3'})
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

	runParams := &leet.RunParams{
		LocalRunParams: &leet.LocalRunParams{
			RunFile: "dummy",
		},
	}
	m := leet.NewRun(runParams, cfg, logger)
	var tm tea.Model = m
	tm, _ = tm.Update(tea.WindowSizeMsg{Width: 160, Height: 60})

	model := tm.(*leet.Run)
	require.True(t, model.TestLeftSidebarVisible())
}

func TestConfig_SetTagColorScheme_Persists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	require.Equal(t, leet.DefaultTagColorScheme, cfg.Snapshot().TagColorScheme)

	err := cfg.SetTagColorScheme("bootstrap-vibe")
	require.NoError(t, err)
	require.Equal(t, "bootstrap-vibe", cfg.TagColorScheme())

	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, "bootstrap-vibe", cfg2.Snapshot().TagColorScheme)
}

func TestConfig_SetSymonGrid_Persists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	require.Equal(t, leet.DefaultSymonGridRows, cfg.Snapshot().SymonGrid.Rows)
	require.Equal(t, leet.DefaultSymonGridCols, cfg.Snapshot().SymonGrid.Cols)

	require.NoError(t, cfg.SetSymonRows(4))
	require.NoError(t, cfg.SetSymonCols(2))

	cfg2 := leet.NewConfigManager(path, logger)
	rows, cols := cfg2.SymonGrid()
	require.Equal(t, 4, rows)
	require.Equal(t, 2, cols)
}

func TestConfig_SetFrenchFriesColorScheme_Persists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	require.Equal(
		t, leet.DefaultFrenchFriesColorScheme, cfg.Snapshot().FrenchFriesColorScheme)

	err := cfg.SetFrenchFriesColorScheme("cividis")
	require.NoError(t, err)
	require.Equal(t, "cividis", cfg.FrenchFriesColorScheme())

	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, "cividis", cfg2.Snapshot().FrenchFriesColorScheme)
}
