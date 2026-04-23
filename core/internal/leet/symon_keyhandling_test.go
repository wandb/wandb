package leet_test

import (
	"path/filepath"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSymon_UnifiedNav_DirectionalAliases(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSymonRows(2)
	_ = cfg.SetSymonCols(2)

	s := leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 200, Height: 80})

	ts := time.Now().Unix()
	// 4 distinct chart groups to populate a 2x2 grid.
	grid := s.TestGrid()
	grid.AddDataPoint("cpu.powerWatts", ts, 25)
	grid.AddDataPoint("gpu.0.powerWatts", ts, 150)
	grid.AddDataPoint("system.powerWatts", ts, 350)
	grid.AddDataPoint("ane.power", ts, 15)
	grid.LoadCurrentPage()

	// Focus (0,0) via click.
	require.True(t, grid.HandleMouseClick(0, 0))
	focus := s.TestFocusState()
	require.Equal(t, 0, focus.Row)
	require.Equal(t, 0, focus.Col)

	_, _ = s.Update(primaryNavMsg(t, leet.NavIntentRight))
	require.Equal(t, 1, focus.Col, "the primary right binding should advance focus")

	require.True(t, grid.HandleMouseClick(0, 0))
	_, _ = s.Update(secondaryNavMsg(t, leet.NavIntentRight))
	require.Equal(t, 1, focus.Col, "the secondary right binding should match the primary binding")
}

func TestSymon_UnifiedNav_PageAndBoundaryKeys(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSymonRows(1)
	_ = cfg.SetSymonCols(1)

	s := leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	ts := time.Now().Unix()
	grid := s.TestGrid()
	grid.AddDataPoint("cpu.powerWatts", ts, 25)
	grid.AddDataPoint("gpu.0.powerWatts", ts, 150)
	grid.AddDataPoint("system.powerWatts", ts, 350)
	grid.LoadCurrentPage()

	_, _ = s.Update(primaryNavMsg(t, leet.NavIntentPageDown))
	require.Equal(t, 1, grid.TestNavigatorCurrentPage(),
		"the primary page-down binding should advance one page")

	_, _ = s.Update(secondaryNavMsg(t, leet.NavIntentPageDown))
	require.Equal(t, 2, grid.TestNavigatorCurrentPage(),
		"the secondary page-down binding should match the primary binding")

	_, _ = s.Update(secondaryNavMsg(t, leet.NavIntentPageUp))
	require.Equal(t, 1, grid.TestNavigatorCurrentPage(),
		"the secondary page-up binding should rewind one page")

	_, _ = s.Update(primaryNavMsg(t, leet.NavIntentHome))
	require.Equal(t, 0, grid.TestNavigatorCurrentPage(),
		"Home should jump back to first page")

	_, _ = s.Update(primaryNavMsg(t, leet.NavIntentEnd))
	require.Equal(t, 2, grid.TestNavigatorCurrentPage(),
		"End should jump to last page")
}

func TestSymon_KeyYCyclesFocusedChartMode(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	s := leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	ts := time.Now().Unix()
	grid := s.TestGrid()
	grid.AddDataPoint("gpu.0.gpu", ts, 25)
	require.True(t, grid.HandleMouseClick(0, 0))
	require.Equal(t, "", grid.FocusedChartScaleLabel())

	_, _ = s.Update(tea.KeyPressMsg{Code: 'y', Text: "y"})
	require.Equal(t, "log y", grid.FocusedChartScaleLabel())

	_, _ = s.Update(tea.KeyPressMsg{Code: 'y', Text: "y"})
	require.Equal(t, "heatmap", grid.FocusedChartScaleLabel())

	_, _ = s.Update(tea.KeyPressMsg{Code: 'y', Text: "y"})
	require.Equal(t, "", grid.FocusedChartScaleLabel())
}
