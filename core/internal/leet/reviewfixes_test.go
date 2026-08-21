package leet

// Regression tests for fixes from the 2026-08 code review.

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// Ctrl+C must quit even while a filter input owns the keyboard.
func TestCtrlCQuitsDuringFilterInput(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "cfg.json"), logger)

	w := NewWorkspace(t.TempDir(), cfg, logger)
	w.handleWindowResize(200, 60)
	w.filter.Activate()
	if cmd := w.handleKeyPressMsg(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl}); cmd == nil {
		t.Fatal("workspace: ctrl+c in filter mode returned no command")
	}

	r := NewRun(&RunParams{RunFile: "unused"}, cfg, logger)
	r.metricsGrid.EnterFilterMode()
	if cmd := r.handleKeyPressMsg(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl}); cmd == nil {
		t.Fatal("run: ctrl+c in filter mode returned no command")
	}
}
