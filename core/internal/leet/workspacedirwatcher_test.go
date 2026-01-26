package leet_test

import (
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestWorkspace_PinSelectsAndPinsWhenNotSelected(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	run1 := "run-20250731_170606-iazb7i1k"
	w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{run1}})

	require.Equal(t, 0, w.TestSelectedRunCount())
	require.Equal(t, "", w.TestPinnedRun())

	// Pin should select + pin (regression test for select-then-unpin bug).
	w.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'p'}})

	require.Equal(t, 1, w.TestSelectedRunCount())
	require.True(t, w.TestIsRunSelected(run1))
	require.Equal(t, run1, w.TestPinnedRun())
}

func TestWorkspace_SelectAndPinRuns_StateTransitions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	run1 := "run-20250731_170606-iazb7i1k"
	run2 := "run-20250731_170607-zzzzzzzz"
	w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{run1, run2}})

	// Select first run.
	w.Update(tea.KeyMsg{Type: tea.KeySpace})
	require.Equal(t, 1, w.TestSelectedRunCount())
	require.True(t, w.TestIsRunSelected(run1))
	require.Equal(t, run1, w.TestPinnedRun())

	// Move to second run + select it.
	w.Update(tea.KeyMsg{Type: tea.KeyDown})
	require.Equal(t, run2, w.TestCurrentRunKey())

	w.Update(tea.KeyMsg{Type: tea.KeySpace})
	require.Equal(t, 2, w.TestSelectedRunCount())
	require.True(t, w.TestIsRunSelected(run2))
	require.Equal(t, run1, w.TestPinnedRun(), "auto-pin stays on first selection until explicitly pinned")

	// Pin the second run.
	w.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'p'}})
	require.Equal(t, run2, w.TestPinnedRun())

	// Deselect pinned run => pin clears (current behavior).
	w.Update(tea.KeyMsg{Type: tea.KeySpace})
	require.Equal(t, 1, w.TestSelectedRunCount())
	require.False(t, w.TestIsRunSelected(run2))
	require.Equal(t, "", w.TestPinnedRun())
}

func TestWorkspace_RunOverviewPreloads_BoundedConcurrency(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	runKeys := []string{
		"run-20250731_170606-a1aaaaaa",
		"run-20250731_170607-b2bbbbbb",
		"run-20250731_170608-c3cccccc",
		"run-20250731_170609-d4dddddd",
		"run-20250731_170610-e5eeeeee",
		"run-20250731_170611-f6ffffff",
		"run-20250731_170612-g7gggggg",
	}

	// Seeds queue and starts up to maxConcurrentPreloads immediately.
	w.Update(leet.WorkspaceRunDirsMsg{RunKeys: runKeys})

	require.Equal(t, 4, w.TestRunOverviewPreloadsInFlight())
	require.Equal(t, 3, w.TestRunOverviewPreloadQueueLen())

	// Simulate completions in FIFO order; inFlight should stay at 4 until fewer remain.
	for i, runKey := range runKeys {
		w.Update(leet.WorkspaceRunOverviewPreloadedMsg{
			RunKey: runKey,
			Run:    leet.RunMsg{ID: "ok"}, // non-empty => treated as success
		})

		remaining := len(runKeys) - (i + 1)
		wantInFlight := min(remaining, 4)
		require.Equal(t, wantInFlight, w.TestRunOverviewPreloadsInFlight())
	}

	require.Equal(t, 0, w.TestRunOverviewPreloadQueueLen())
	require.Equal(t, 0, w.TestRunOverviewPreloadsInFlight())
}
