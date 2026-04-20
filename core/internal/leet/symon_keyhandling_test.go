package leet

import (
	"path/filepath"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

// TestSymon_ArrowsMoveChartFocus verifies arrow keys move chart focus
// within the current page just like wasd.
func TestSymon_ArrowsMoveChartFocus(t *testing.T) {
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

	// Right arrow should advance column like 'd'.
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyRight})
	require.Equal(t, 1, focus.Col, "Right arrow should advance focus one column")

	// Down arrow should advance row like 's'.
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	require.Equal(t, 1, focus.Row, "Down arrow should advance focus one row")
}

// TestSymon_PgUpN_JumpsToPrevPage verifies that both PgUp and 'N' invoke
// handlePrevPage.
func TestSymon_PgUpN_JumpsToPrevPage(t *testing.T) {
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

	// Advance to last page, then rewind with PgUp.
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
	require.Equal(t, 2, s.grid.TestNavigatorCurrentPage())

	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyPgUp})
	require.Equal(t, 1, s.grid.TestNavigatorCurrentPage(),
		"PgUp should go back one page")

	// Shift+N -> capital N, same as PgUp.
	_, _ = s.Update(tea.KeyPressMsg{Code: 'N', Text: "N"})
	require.Equal(t, 0, s.grid.TestNavigatorCurrentPage(),
		"'N' should go back one page, same as PgUp")
}

// TestSymon_HomeEndJumpsBetweenPages verifies that Home/End jump to
// first/last page of the grid.
func TestSymon_HomeEndJumpsBetweenPages(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSymonRows(1)
	_ = cfg.SetSymonCols(1)

	s := NewSymon(SymonParams{Config: cfg, Logger: logger})
	defer s.Cleanup()

	_, _ = s.Update(tea.WindowSizeMsg{Width: 140, Height: 45})

	ts := time.Now().Unix()
	// 3 distinct chart groups -> 3 pages at 1x1 grid.
	s.grid.AddDataPoint("cpu.powerWatts", ts, 25)
	s.grid.AddDataPoint("gpu.0.powerWatts", ts, 150)
	s.grid.AddDataPoint("system.powerWatts", ts, 350)
	s.grid.LoadCurrentPage()

	// Advance to page 2 (last).
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyPgDown})
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyPgDown})
	require.Equal(t, 2, s.grid.TestNavigatorCurrentPage())

	// Home returns to page 0.
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyHome})
	require.Equal(t, 0, s.grid.TestNavigatorCurrentPage(),
		"Home should jump back to first page")

	// End jumps to the last page.
	_, _ = s.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
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
