package leet_test

import (
	"os"
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

const (
	deleteTestRunKey = "run-20260101_000000-abc123"
	deleteTestRunID  = "abc123"
)

// newWorkspaceWithRunDir builds a workspace over a wandb dir that contains a
// single real run directory, with the runs list focused on it.
func newWorkspaceWithRunDir(t *testing.T) (*leet.Workspace, string) {
	t.Helper()
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	runDir := filepath.Join(wandbDir, deleteTestRunKey)
	require.NoError(t, os.MkdirAll(runDir, 0o755))
	require.NoError(t, os.WriteFile(
		filepath.Join(runDir, "run-"+deleteTestRunID+".wandb"), []byte("x"), 0o644))

	w := leet.NewWorkspace(wandbDir, cfg, logger)
	_ = w.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	_ = w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{deleteTestRunKey}})
	return w, runDir
}

func pressKey(w *leet.Workspace, code rune) tea.Cmd {
	return w.Update(tea.KeyPressMsg{Code: code})
}

func TestWorkspace_DeleteRun_Confirmed(t *testing.T) {
	w, runDir := newWorkspaceWithRunDir(t)

	require.Nil(t, pressKey(w, tea.KeyBackspace))
	require.True(t, w.IsConfirmingDelete(), "expected modal open after backspace")

	typeWorkspaceFilter(t, w, "DELETE")
	cmd := pressKey(w, tea.KeyEnter)
	require.NotNil(t, cmd, "expected a delete command after typed confirmation")

	msg := cmd()
	deleted, ok := msg.(leet.WorkspaceRunDeletedMsg)
	require.True(t, ok, "expected WorkspaceRunDeletedMsg, got %T", msg)
	require.NoError(t, deleted.Err)
	require.NoDirExists(t, runDir, "expected run directory removed from disk")

	_ = w.Update(msg)
	require.False(t, w.IsConfirmingDelete(), "expected modal closed after deletion")
	require.Empty(t, w.TestFilteredRunKeys(), "expected run dropped from the list")
	require.Equal(t, 0, w.TestSelectedRunCount())
}

func TestWorkspace_DeleteRun_WrongTextDoesNotDelete(t *testing.T) {
	w, runDir := newWorkspaceWithRunDir(t)

	require.Nil(t, pressKey(w, tea.KeyBackspace))
	require.True(t, w.IsConfirmingDelete())

	// While the modal is open, global bindings must not fire: 'q' is typed
	// text here, not quit.
	typeWorkspaceFilter(t, w, "q")
	require.True(t, w.IsConfirmingDelete())

	require.Nil(t, pressKey(w, tea.KeyEnter), "Enter with wrong text must not delete")
	require.True(t, w.IsConfirmingDelete(), "modal stays open on mismatched text")
	require.DirExists(t, runDir)
}

func TestWorkspace_DeleteRun_EscCancels(t *testing.T) {
	w, runDir := newWorkspaceWithRunDir(t)

	require.Nil(t, pressKey(w, tea.KeyBackspace))
	typeWorkspaceFilter(t, w, "DELETE")
	require.Nil(t, pressKey(w, tea.KeyEsc))

	require.False(t, w.IsConfirmingDelete(), "expected modal closed after Esc")
	require.DirExists(t, runDir)
	require.Equal(t, []string{deleteTestRunKey}, w.TestFilteredRunKeys())

	// Global bindings work again: 'q' quits.
	cmd := w.Update(keyRune('q'))
	require.NotNil(t, cmd)
	require.IsType(t, tea.QuitMsg{}, cmd())
}

func TestWorkspace_DeleteRun_LiveRunBlocked(t *testing.T) {
	w, runDir := newWorkspaceWithRunDir(t)

	// Mark the run as live: a RunMsg record transitions it to running.
	run := leet.TestNewWorkspaceRun(deleteTestRunKey)
	w.TestAttachRun(run, true)
	w.TestHandleWorkspaceRecord(run, leet.RunMsg{ID: deleteTestRunID})

	require.Nil(t, pressKey(w, tea.KeyBackspace))
	require.True(t, w.IsConfirmingDelete())
	require.True(t, w.TestDeleteModalBlocked(), "expected modal blocked for a live run")

	// Typing DELETE and pressing Enter must not delete a live run.
	typeWorkspaceFilter(t, w, "DELETE")
	require.Nil(t, pressKey(w, tea.KeyEnter))
	require.False(t, w.IsConfirmingDelete(), "Enter closes the blocked modal")
	require.DirExists(t, runDir)
}

func TestWorkspace_DeleteRun_FailureKeepsModalOpen(t *testing.T) {
	w, runDir := newWorkspaceWithRunDir(t)

	require.Nil(t, pressKey(w, tea.KeyBackspace))
	typeWorkspaceFilter(t, w, "DELETE")
	require.NotNil(t, pressKey(w, tea.KeyEnter))

	// Simulate a failed removal.
	_ = w.Update(leet.WorkspaceRunDeletedMsg{
		RunKey: deleteTestRunKey,
		Err:    os.ErrPermission,
	})
	require.True(t, w.IsConfirmingDelete(), "expected modal open after failed delete")
	require.NotEmpty(t, w.TestDeleteModalError())
	require.Equal(t, []string{deleteTestRunKey}, w.TestFilteredRunKeys(),
		"run stays listed after failed delete")
	require.DirExists(t, runDir)

	// Esc dismisses the error.
	require.Nil(t, pressKey(w, tea.KeyEsc))
	require.False(t, w.IsConfirmingDelete())
}

func TestModel_DeleteRunConfirmEnterDoesNotEnterRunView(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	wandbDir := t.TempDir()
	runDir := filepath.Join(wandbDir, deleteTestRunKey)
	require.NoError(t, os.MkdirAll(runDir, 0o755))
	require.NoError(t, os.WriteFile(
		filepath.Join(runDir, "run-"+deleteTestRunID+".wandb"), []byte("x"), 0o644))

	m := leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})
	_, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	_, _ = m.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{deleteTestRunKey}})

	_, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyBackspace})
	for _, r := range "DELETE" {
		_, _ = m.Update(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
	_, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	require.False(t, m.TestInRunMode(),
		"Enter confirming a delete must not switch to the run view")
}
