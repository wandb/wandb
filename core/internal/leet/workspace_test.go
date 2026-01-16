package leet_test

import (
	"os"
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestModel_WorkspaceFilterDoesNotLeakIntoRunView(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	runDir := "run-20250731_170606-iazb7i1k"
	runFile := filepath.Join(wandbDir, runDir, "run-iazb7i1k.wandb")
	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))
	require.NoError(t, os.WriteFile(runFile, nil, 0o644))

	var model tea.Model = leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})

	// Seed workspace run list.
	model, _ = model.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runDir}})
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Workspace: set metrics filter to "train".
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	for _, r := range "train" {
		model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
	}
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter}) // apply

	// Enter run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Run view: apply metrics filter "x".
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'x'}})
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Exit run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEsc})

	// Workspace filter must remain "train" (not "trainx").
	view := stripANSI(model.View())
	require.Contains(t, view, `"train"`)
	require.NotContains(t, view, `"trainx"`)
}

func TestModel_CtrlLInRunViewDoesNotClearWorkspaceFilter(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	runDir := "run-20250731_170606-iazb7i1k"
	runFile := filepath.Join(wandbDir, runDir, "run-iazb7i1k.wandb")
	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))
	require.NoError(t, os.WriteFile(runFile, nil, 0o644))

	var model tea.Model = leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})

	model, _ = model.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{runDir}})
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Workspace: set filter to "train".
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'/'}})
	for _, r := range "train" {
		model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{r}})
	}
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Enter run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Clear filter in run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyCtrlL})

	// Exit run view.
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyEsc})

	view := stripANSI(model.View())
	require.Contains(t, view, `"train"`)
}
