package leet_test

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func expandRightSidebar(t *testing.T, rs *leet.RightSidebar, termWidth int, leftVisible bool) {
	t.Helper()
	rs.UpdateDimensions(termWidth, leftVisible)
	rs.Toggle()
	time.Sleep(leet.AnimationDuration + 20*time.Millisecond)
	rs.Update(leet.RightSidebarAnimationMsg{})
}

func TestRightSidebar_UpdateDimensions_ToggleAndViewHeader(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_, _ = cfg.SetSystemRows(1), cfg.SetSystemCols(1)
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)

	rs := leet.NewRightSidebar(cfg, &leet.Focus{}, logger)

	termWidth := 200
	expandRightSidebar(t, rs, termWidth, false)

	// Width should equal clamped int(termWidth * SidebarWidthRatio).
	want := min(
		max(int(float64(termWidth)*leet.SidebarWidthRatio), leet.SidebarMinWidth),
		leet.SidebarMaxWidth,
	)
	require.Equal(t, want, rs.Width())

	// Ensure View renders header text once visible and grid ensured.
	view := rs.View(20)
	require.NotEmpty(t, view)
	require.Contains(t, view, "System Metrics")
}

func TestRightSidebar_HandleMouseClick_FocusToggleAndClear(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_, _ = cfg.SetSystemRows(1), cfg.SetSystemCols(1)
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)

	rs := leet.NewRightSidebar(cfg, &leet.Focus{}, logger)
	expandRightSidebar(t, rs, 160, false)

	// Feed stats so a chart exists on the first cell.
	ts := time.Now().Unix()
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"cpu.0.cpu_percent": 50,
		},
	})

	// Click near the top-left accounting for border/padding (1,1 maps to row/col 0).
	ok := rs.HandleMouseClick(1, 1)
	require.True(t, ok, "expected focus to be set")
	require.NotEmpty(t, rs.FocusedChartTitle())

	// Clicking the same location toggles focus off through the grid.
	ok2 := rs.HandleMouseClick(1, 1)
	require.False(t, ok2, "expected focus to be cleared")
	require.Empty(t, rs.FocusedChartTitle())

	// Explicit clear also leaves no focus.
	rs.ClearFocus()
	require.Empty(t, rs.FocusedChartTitle())
}

func TestRightSidebar_HeaderShowsPaginationInfo(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	// 1x1 grid -> ItemsPerPage == 1, so multiple charts produce pagination info.
	_, _ = cfg.SetSystemRows(1), cfg.SetSystemCols(1)
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)

	rs := leet.NewRightSidebar(cfg, &leet.Focus{}, logger)
	expandRightSidebar(t, rs, 140, false)

	ts := time.Now().Unix()
	rs.ProcessStatsMsg(leet.StatsMsg{
		Timestamp: ts,
		Metrics: map[string]float64{
			"gpu.0.temp":        40, // base "gpu.temp"
			"cpu.0.cpu_percent": 50, // base "cpu.cpu_percent"
			"memory_percent":    65, // base "memory_percent"
		},
	})

	view := rs.View(12)
	require.Contains(t, view, "System Metrics")
	// Header includes "[start-end of total]".
	require.Contains(t, view, "[1-1 of 3]")
}

func TestRightSidebar_Update_ReturnsAnimationCmdWhileAnimating(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	rs := leet.NewRightSidebar(cfg, &leet.Focus{}, logger)

	// Start expansion; immediately update -> should get a continuation command.
	rs.UpdateDimensions(120, false)
	rs.Toggle()
	_, cmd := rs.Update(leet.RightSidebarAnimationMsg{})
	require.NotNil(t, cmd, "expected a continuation command while animating")

	// After the animation window, update should finish and return nil.
	time.Sleep(leet.AnimationDuration + 10*time.Millisecond)
	_, cmd = rs.Update(leet.RightSidebarAnimationMsg{})
	require.Nil(t, cmd, "no continuation command expected after animation completes")
	require.False(t, rs.IsAnimating())
}
