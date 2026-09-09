package leet_test

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSymon_ConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	for _, tc := range []struct {
		name string
		key  rune
		rows int
		cols int
	}{
		{name: "rows", key: 'r', rows: 4, cols: 3},
		{name: "columns", key: 'c', rows: 3, cols: 4},
	} {
		t.Run(tc.name, func(t *testing.T) {
			logger := observability.NewNoOpLogger()
			cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
			require.NoError(t, cfg.SetSymonRows(3))
			require.NoError(t, cfg.SetSymonCols(3))

			s := leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
			defer s.Cleanup()
			var m tea.Model = s
			// Both the original and enlarged grids fit without a terminal resize.
			m, _ = m.Update(tea.WindowSizeMsg{Width: 188, Height: 60})
			m, _ = m.Update(leet.StatsMsg{
				Timestamp: 100,
				Metrics: map[string]float64{
					"gpu.0.temp": 40,
				},
			})
			require.Contains(t, m.View().Content, "GPU Temp")

			// Grow, then shrink, without sending another sample or resize event.
			for _, key := range []rune{'4', '1'} {
				m, _ = m.Update(tea.KeyPressMsg{Code: tc.key})
				m, _ = m.Update(tea.KeyPressMsg{Code: key})
				wantRows, wantCols := tc.rows, tc.cols
				if key == '1' {
					if tc.key == 'r' {
						wantRows = 1
					} else {
						wantCols = 1
					}
				}
				rows, cols := cfg.SymonGrid()
				require.Equal(t, wantRows, rows)
				require.Equal(t, wantCols, cols)

				// The key handler must reflow and redraw before Update returns.
				grid := s.TestGrid()
				page := grid.TestCurrentPage()
				require.Len(t, page, wantRows)
				for _, row := range page {
					require.Len(t, row, wantCols)
				}
				chart := grid.TestChartAt(0, 0)
				require.NotNil(t, chart)
				// 186x58 is the viewport after padding, header, and status bar.
				require.Equal(t, 186/wantCols-leet.ChartBorderSize, chart.Width())
				require.Equal(
					t, 58/wantRows-leet.ChartBorderSize-leet.ChartTitleHeight, chart.Height())
				chartView := chart.View()
				require.Equal(t, chart.Width(), lipgloss.Width(chartView))
				require.Equal(t, chart.Height(), lipgloss.Height(chartView))

				var view string
				require.NotPanics(t, func() { view = m.View().Content })
				require.Contains(t, view, "GPU Temp")
			}
		})
	}
}

func TestSymon_FilterLifecycle(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m, _ = m.Update(leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"cpu.0.cpu_percent": 50,
		},
	})

	m, _ = m.Update(tea.KeyPressMsg{Code: '\\', Text: "\\"})
	m, _ = m.Update(tea.KeyPressMsg{Code: 'G', Text: "G"})
	m, _ = m.Update(tea.KeyPressMsg{Code: 'P', Text: "P"})
	m, _ = m.Update(tea.KeyPressMsg{Code: 'U', Text: "U"})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	view := m.View().Content
	require.Contains(t, view, "GPU Temp")
	require.NotContains(t, view, "CPU Core")
}
