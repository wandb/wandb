package leet_test

import (
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSymon_ConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m, _ = m.Update(leet.StatsMsg{
		Timestamp: 100,
		Metrics:   map[string]float64{"gpu.0.temp": 40},
	})

	m, _ = m.Update(tea.KeyPressMsg{Code: 'r'})
	m, _ = m.Update(tea.KeyPressMsg{Code: '5'})
	rows, _ := cfg.SymonGrid()
	require.Equal(t, 5, rows)
	require.Contains(t, m.View().Content, "GPU Temp")

	m, _ = m.Update(tea.KeyPressMsg{Code: 'c'})
	m, _ = m.Update(tea.KeyPressMsg{Code: '4'})
	_, cols := cfg.SymonGrid()
	require.Equal(t, 4, cols)
	require.Contains(t, m.View().Content, "GPU Temp")
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

func TestSymon_FirstPageOrderAndHeatmap(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 160, Height: 45})
	m, _ = m.Update(leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"memory_percent":    50,
			"cpu.0.cpu_percent": 20,
			"cpu.1.cpu_percent": 60,
		},
	})

	view := m.View().Content
	cores := strings.Index(view, "CPU Core (%)")
	memory := strings.Index(view, "System Memory (%)")
	gpu := strings.Index(view, "GPU Temp")
	require.True(t, cores >= 0 && cores < memory && memory < gpu, view)
	require.Contains(t, view, "[heatmap]")
}

func TestSymon_HeaderShowsUptimeAndLoad(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m, _ = m.Update(leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"memory_percent": 50,
			"system.uptime":  93600 + 5*60,
			"system.load1":   1.5,
			"system.load5":   0.8,
			"system.load15":  0.6,
		},
	})

	require.Contains(t, m.View().Content, "up 1d 2h • load 1.50 0.80 0.60")
}
