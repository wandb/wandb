package leet_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSystemMetricsGrid_Filter(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(1)
	_ = cfg.SetSystemCols(2)

	grid := leet.NewSystemMetricsGrid(
		80,
		24,
		cfg,
		cfg.SystemGrid,
		leet.NewFocus(),
		leet.NewFilter(),
		logger,
	)

	grid.AddDataPoint("gpu.0.temp", 100, 40)
	grid.AddDataPoint("cpu.0.cpu_percent", 100, 50)
	require.Equal(t, 2, grid.ChartCount())
	require.Equal(t, 2, grid.FilteredChartCount())

	grid.EnterFilterMode()
	require.True(t, grid.IsFilterMode())

	typeString(grid, "GPU")
	grid.ApplyFilter()
	require.Equal(t, "GPU", grid.FilterQuery())
	require.Equal(t, 1, grid.FilteredChartCount())

	// Live preview should hide non-matching charts.
	view := grid.View()
	require.Contains(t, view, "GPU Temp")
	require.NotContains(t, view, "CPU Util")

	grid.ExitFilterMode(true)
	require.False(t, grid.IsFilterMode())
	require.True(t, grid.IsFiltering())
	require.Equal(t, "GPU", grid.FilterQuery())
	require.Equal(t, 1, grid.FilteredChartCount())

	grid.ClearFilter()
	require.False(t, grid.IsFiltering())
	require.Equal(t, "", grid.FilterQuery())
	require.Equal(t, 2, grid.FilteredChartCount())
}
