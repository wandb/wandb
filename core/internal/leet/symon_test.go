package leet_test

import (
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestSymon_ConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m, _ = m.Update(leet.SymonSampleMsg{StatsMsg: leet.StatsMsg{
		Timestamp: 100,
		Metrics:   map[string]float64{"gpu.0.temp": 40},
	}})

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
	m, _ = m.Update(leet.SymonSampleMsg{StatsMsg: leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"cpu.0.cpu_percent": 50,
		},
	}})

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
	m, _ = m.Update(leet.SymonSampleMsg{StatsMsg: leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"gpu.0.temp":        40,
			"memory_percent":    50,
			"cpu.0.cpu_percent": 20,
			"cpu.1.cpu_percent": 60,
		},
	}})

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
	m, _ = m.Update(leet.SymonSampleMsg{StatsMsg: leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"memory_percent": 50,
			"system.uptime":  93600 + 5*60,
			"system.load1":   1.5,
			"system.load5":   0.8,
			"system.load15":  0.6,
		},
	}})

	require.Contains(t, m.View().Content, "up 1d 2h • load 1.50 0.80 0.60")
}

func TestSymon_SidebarMetersAndToggle(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 160, Height: 45})
	m, _ = m.Update(leet.SymonSampleMsg{StatsMsg: leet.StatsMsg{
		Timestamp: 100,
		Metrics: map[string]float64{
			"memory_percent":    50,
			"cpu.0.cpu_percent": 20,
			"cpu.1.cpu_percent": 60,
		},
	}})

	cpuMeter := regexp.MustCompile(`CPU\s+\S+\s+40%`)
	require.Regexp(t, cpuMeter, stripANSI(m.View().Content))

	m, _ = m.Update(tea.KeyPressMsg{Code: '[', Text: "["})
	require.NotRegexp(t, cpuMeter, stripANSI(m.View().Content))
	require.False(t, cfg.SymonSidebarVisible())
}

func TestSymon_ProcessesSortedByCPUThenMemory(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 160, Height: 45})
	m, _ = m.Update(leet.SymonSampleMsg{
		StatsMsg: leet.StatsMsg{Timestamp: 100, Metrics: map[string]float64{"memory_percent": 50}},
		Processes: []monitor.ProcessStat{
			{PID: 1, Name: "chrome", CPUPercent: 10, RSS: 8 << 30},
			{PID: 2, Name: "python", CPUPercent: 300, RSS: 1 << 30},
		},
	})

	view := m.View().Content
	require.Contains(t, view, "python")
	require.Less(t, strings.Index(view, "python"), strings.Index(view, "chrome"))

	m, _ = m.Update(tea.KeyPressMsg{Code: 't', Text: "t"})
	view = m.View().Content
	require.Less(t, strings.Index(view, "chrome"), strings.Index(view, "python"))
}

func TestSymon_ProcessFilterAndFocus(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	sym := leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	var m tea.Model = sym
	m, _ = m.Update(tea.WindowSizeMsg{Width: 160, Height: 45})
	m, _ = m.Update(leet.SymonSampleMsg{
		StatsMsg: leet.StatsMsg{Timestamp: 100, Metrics: map[string]float64{"memory_percent": 50}},
		Processes: []monitor.ProcessStat{
			{PID: 1, Name: "chrome", CPUPercent: 10, RSS: 8 << 30},
			{PID: 2, Name: "python", CPUPercent: 300, RSS: 1 << 30},
		},
	})

	for _, key := range []rune{'f', 'p', 'y', 't', 'h'} {
		m, _ = m.Update(tea.KeyPressMsg{Code: key, Text: string(key)})
	}
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	view := m.View().Content
	require.Contains(t, view, "python")
	require.NotContains(t, view, "chrome")

	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	m, _ = m.Update(tea.KeyPressMsg{Code: 's', Text: "s"})
	require.Equal(t, leet.FocusNone, sym.TestFocusState().Type,
		"navigation keys stay in the process list while it has focus")

	_, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	require.Equal(t, leet.FocusSystemChart, sym.TestFocusState().Type)
}

func TestSymon_RunsPaneAttributesProcessTree(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewSymon(leet.SymonParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 220, Height: 45})
	m, _ = m.Update(leet.SymonSampleMsg{
		StatsMsg: leet.StatsMsg{Timestamp: 100, Metrics: map[string]float64{"memory_percent": 50}},
		Processes: []monitor.ProcessStat{
			{PID: 10, PPID: 1, Name: "python", CPUPercent: 100, RSS: 1 << 30},
			{PID: 11, PPID: 10, Name: "python", CPUPercent: 250, RSS: 2 << 30},
			{PID: 12, PPID: 10, Name: "wandb-core", CPUPercent: 5, RSS: 1 << 20},
		},
		Runs: []leet.SymonRun{{
			LiveRun: monitor.LiveRun{
				Path:      "/tmp/proj/wandb/run-20260928_150000-abc123/run-abc123.wandb",
				PID:       12,
				ClientPID: 10,
			},
			Name:    "dazzling-owl-42",
			Project: "nlp",
			Step:    1200,
			Metric:  "loss",
			Values:  []float64{2, 1.5, 1.1, 0.8},
		}},
	})

	view := stripANSI(m.View().Content)
	require.Contains(t, view, "dazzling-owl-42")
	require.Contains(t, view, "step 1200")
	require.Regexp(t, `loss\s+0\.8\s+█▅▂▁`, view)
	require.Regexp(t, `CPU\s+355%`, view)
	require.Contains(t, view, "3GiB")

	m, _ = m.Update(tea.KeyPressMsg{Code: '1', Text: "1"})
	require.NotContains(t, stripANSI(m.View().Content), "dazzling-owl-42")
}
