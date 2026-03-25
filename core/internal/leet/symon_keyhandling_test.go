package leet

import (
	"path/filepath"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

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
