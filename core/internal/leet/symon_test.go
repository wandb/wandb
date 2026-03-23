package leet_test

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSymon_ConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(cfg, logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m, _ = m.Update(tea.KeyPressMsg{Code: 'r'})
	m, _ = m.Update(tea.KeyPressMsg{Code: '5'})
	rows, _ := cfg.SymonGrid()
	require.Equal(t, 5, rows)

	m, _ = m.Update(tea.KeyPressMsg{Code: 'c'})
	_, _ = m.Update(tea.KeyPressMsg{Code: '4'})
	_, cols := cfg.SymonGrid()
	require.Equal(t, 4, cols)
}

func TestSymon_FilterLifecycle(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(cfg, logger)
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
