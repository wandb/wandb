package leet

import (
	"path/filepath"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

func TestSymon_UnifiedNav_DirectionalAliases(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSymonRows(2)
	_ = cfg.SetSymonCols(2)

	s := NewSymon(SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 200, Height: 80})

	ts := time.Now().Unix()
	// 4 distinct chart groups to populate a 2x2 grid.
	s.grid.AddDataPoint("cpu.powerWatts", ts, 25)
	s.grid.AddDataPoint("gpu.0.powerWatts", ts, 150)
	s.grid.AddDataPoint("system.powerWatts", ts, 350)
	s.grid.AddDataPoint("ane.power", ts, 15)
	s.grid.LoadCurrentPage()

	// Focus (0,0) via click.
	require.True(t, s.grid.HandleMouseClick(0, 0))
	focus := s.focus
	require.Equal(t, 0, focus.Row)
	require.Equal(t, 0, focus.Col)

	_, _ = s.Update(testPrimaryNavMsg(t, NavIntentRight))
	require.Equal(t, 1, focus.Col, "the primary right binding should advance focus")

	require.True(t, s.grid.HandleMouseClick(0, 0))
	_, _ = s.Update(testSecondaryNavMsg(t, NavIntentRight))
	require.Equal(t, 1, focus.Col, "the secondary right binding should match the primary binding")
}

func TestSymon_UnifiedNav_PageAndBoundaryKeys(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSymonRows(1)
	_ = cfg.SetSymonCols(1)

	s := NewSymon(SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	ts := time.Now().Unix()
	s.grid.AddDataPoint("cpu.powerWatts", ts, 25)
	s.grid.AddDataPoint("gpu.0.powerWatts", ts, 150)
	s.grid.AddDataPoint("system.powerWatts", ts, 350)
	s.grid.LoadCurrentPage()

	_, _ = s.Update(testPrimaryNavMsg(t, NavIntentPageDown))
	require.Equal(t, 1, s.grid.TestNavigatorCurrentPage(),
		"the primary page-down binding should advance one page")

	_, _ = s.Update(testSecondaryNavMsg(t, NavIntentPageDown))
	require.Equal(t, 2, s.grid.TestNavigatorCurrentPage(),
		"the secondary page-down binding should match the primary binding")

	_, _ = s.Update(testSecondaryNavMsg(t, NavIntentPageUp))
	require.Equal(t, 1, s.grid.TestNavigatorCurrentPage(),
		"the secondary page-up binding should rewind one page")

	_, _ = s.Update(testPrimaryNavMsg(t, NavIntentHome))
	require.Equal(t, 0, s.grid.TestNavigatorCurrentPage(),
		"Home should jump back to first page")

	_, _ = s.Update(testPrimaryNavMsg(t, NavIntentEnd))
	require.Equal(t, 2, s.grid.TestNavigatorCurrentPage(),
		"End should jump to last page")
}

func TestSymon_KeyYCyclesFocusedChartMode(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	s := NewSymon(SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	ts := time.Now().Unix()
	s.grid.AddDataPoint("gpu.0.gpu", ts, 25)
	require.True(t, s.grid.HandleMouseClick(0, 0))
	require.Equal(t, "", s.grid.FocusedChartScaleLabel())

	_, _ = s.Update(tea.KeyPressMsg{Code: 'y', Text: "y"})
	require.Equal(t, "log y", s.grid.FocusedChartScaleLabel())

	_, _ = s.Update(tea.KeyPressMsg{Code: 'y', Text: "y"})
	require.Equal(t, "heatmap", s.grid.FocusedChartScaleLabel())

	_, _ = s.Update(tea.KeyPressMsg{Code: 'y', Text: "y"})
	require.Equal(t, "", s.grid.FocusedChartScaleLabel())
}
