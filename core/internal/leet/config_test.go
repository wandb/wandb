package leet_test

import (
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestConfigHotkeys_UpdateGridDimensions(t *testing.T) {
	// Not parallel: touches global config & exported grid vars.
	tmp := t.TempDir()
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(tmp, "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("config.Load: %v", err)
	}

	var m tea.Model = leet.NewModel("dummy", observability.NewNoOpLogger())
	// Ensure model is sized so internal recomputations run.
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// metrics rows: 'r' then '5'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'5'}})
	gridRows, _ := cfg.GetMetricsGrid()
	if gridRows != 5 {
		t.Fatalf("GridRows=%d; want 5", gridRows)
	}

	// metrics cols: 'c' then '4'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'c'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'4'}})
	_, gridCols := cfg.GetMetricsGrid()
	if gridCols != 4 {
		t.Fatalf("GridCols=%d; want 4", gridCols)
	}

	// system rows: 'R' then '2'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'R'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'2'}})
	gridRows, _ = cfg.GetSystemGrid()
	if gridRows != 2 {
		t.Fatalf("MetricsGridRows=%d; want 2", gridRows)
	}

	// system cols: 'C' then '3'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'C'}})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'3'}})
	_, gridCols = cfg.GetSystemGrid()
	if gridCols != 3 {
		t.Fatalf("MetricsGridCols=%d; want 3", gridCols)
	}
}

func TestConfig_SetLeftSidebarVisible_TogglesAndPersists(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	cfg := leet.GetConfig()
	cfg.SetPathForTests(path)
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}

	// Toggle on
	if err := cfg.SetLeftSidebarVisible(true); err != nil {
		t.Fatalf("SetLeftSidebarVisible(true): %v", err)
	}
	if !cfg.GetLeftSidebarVisible() {
		t.Fatalf("GetLeftSidebarVisible() = false; want true")
	}

	// Toggle off
	if err := cfg.SetLeftSidebarVisible(false); err != nil {
		t.Fatalf("SetLeftSidebarVisible(false): %v", err)
	}
	if cfg.GetLeftSidebarVisible() {
		t.Fatalf("GetLeftSidebarVisible() = true; want false")
	}
}

func TestConfig_SetLeftSidebarVisible_AffectsModelOnStartup(t *testing.T) {
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	if err := cfg.SetLeftSidebarVisible(true); err != nil {
		t.Fatalf("SetLeftSidebarVisible: %v", err)
	}

	logger := observability.NewNoOpLogger()
	m := leet.NewModel("dummy", logger)
	var tm tea.Model = m
	tm, _ = tm.Update(tea.WindowSizeMsg{Width: 160, Height: 60})

	model := tm.(*leet.Model)
	if !model.TestLeftSidebarVisible() {
		t.Fatalf("left sidebar should be visible when config flag is true")
	}
}
