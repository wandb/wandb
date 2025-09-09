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
	if leet.GridRows != 5 {
		t.Fatalf("GridRows=%d; want 5", leet.GridRows)
	}

	// metrics cols: 'c' then '4'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'c'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'4'}})
	if leet.GridCols != 4 {
		t.Fatalf("GridCols=%d; want 4", leet.GridCols)
	}

	// system rows: 'R' then '2'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'R'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'2'}})
	if leet.MetricsGridRows != 2 {
		t.Fatalf("MetricsGridRows=%d; want 2", leet.MetricsGridRows)
	}

	// system cols: 'C' then '3'
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'C'}})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'3'}})
	if leet.MetricsGridCols != 3 {
		t.Fatalf("MetricsGridCols=%d; want 3", leet.MetricsGridCols)
	}
}
