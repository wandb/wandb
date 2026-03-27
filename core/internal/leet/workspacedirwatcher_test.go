package leet_test

import (
	"os"
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func createRunWandbFile(t *testing.T, wandbDir, runKey string, records []*spb.Record) {
	t.Helper()

	runID := leet.TestExtractRunID(runKey)
	require.NotEmpty(t, runID, "could not extract run ID from key %q", runKey)

	runDir := filepath.Join(wandbDir, runKey)
	require.NoError(t, os.MkdirAll(runDir, 0o755))

	wandbFile := filepath.Join(runDir, "run-"+runID+".wandb")
	w, err := transactionlog.OpenWriter(wandbFile)
	require.NoError(t, err)

	for _, rec := range records {
		require.NoError(t, w.Write(rec))
	}
	require.NoError(t, w.Close())
}

func TestWorkspace_PinSelectsAndPinsWhenNotSelected(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	require.Equal(t, 0, w.TestSelectedRunCount())

	run1 := "run-20250731_170606-iazb7i1k"
	w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{run1}})

	require.Equal(t, 1, w.TestSelectedRunCount()) // autoselect and pin
	require.Equal(t, run1, w.TestPinnedRun())

	// Unpin.
	w.Update(tea.KeyPressMsg{Code: 'p'})

	require.Equal(t, 1, w.TestSelectedRunCount())
	require.True(t, w.TestIsRunSelected(run1))
	require.Equal(t, "", w.TestPinnedRun())
}

func TestWorkspace_SelectAndPinRuns_StateTransitions(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	run1 := "run-20250731_170606-iazb7i1k"
	run2 := "run-20250731_170607-zzzzzzzz"
	w.Update(leet.WorkspaceRunDirsMsg{RunKeys: []string{run1, run2}})

	// First run is autoselected.
	require.Equal(t, 1, w.TestSelectedRunCount())
	require.True(t, w.TestIsRunSelected(run1))
	require.Equal(t, run1, w.TestPinnedRun())

	// Move to second run + select it.
	w.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	require.Equal(t, run2, w.TestCurrentRunKey())

	w.Update(tea.KeyPressMsg{Code: tea.KeySpace})
	require.Equal(t, 2, w.TestSelectedRunCount())
	require.True(t, w.TestIsRunSelected(run2))
	require.Equal(t, run1, w.TestPinnedRun(),
		"auto-pin stays on first selection until explicitly pinned")

	// Pin the second run.
	w.Update(tea.KeyPressMsg{Code: 'p'})
	require.Equal(t, run2, w.TestPinnedRun())

	// Deselect pinned run => pin clears (current behavior).
	w.Update(tea.KeyPressMsg{Code: tea.KeySpace})
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
			Run:    &leet.RunMsg{ID: "ok"}, // non-empty => treated as success
		})

		remaining := len(runKeys) - (i + 1)
		wantInFlight := min(remaining, 4)
		require.Equal(t, wantInFlight, w.TestRunOverviewPreloadsInFlight())
	}

	require.Equal(t, 0, w.TestRunOverviewPreloadQueueLen())
	require.Equal(t, 0, w.TestRunOverviewPreloadsInFlight())
}

func TestWorkspace_PreloadRunOverview_ExtractsRunRecord(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wandbDir := t.TempDir()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	runID := "iazb7i1k"
	runKey := "run-20250731_170606-" + runID
	createRunWandbFile(t, wandbDir, runKey, []*spb.Record{
		{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
			RunId:       runID,
			DisplayName: "test-run",
			Project:     "test-project",
		}}},
	})

	w := leet.NewWorkspace(wandbDir, cfg, logger)

	// call preload command directly and verify the returned message
	msg := w.TestExecutePreloadCmd(runKey)

	require.NoError(t, msg.Err)
	require.NotNil(t, msg.Run)
	require.Equal(t, runID, msg.Run.ID)
	require.Equal(t, "test-run", msg.Run.DisplayName)
	require.Equal(t, "test-project", msg.Run.Project)

	// update the workspace to populate the overview
	w.Update(msg)

	runOverview := w.TestGetRunOverviewByRunKey(runKey)
	require.Equal(t, runID, runOverview.ID())
	require.Equal(t, "test-run", runOverview.DisplayName())
	require.Equal(t, "test-project", runOverview.Project())
}

func TestWorkspace_PreloadRunOverview_AllRunsPopulated(t *testing.T) {
	logger := observability.NewNoOpLogger()
	wandbDir := t.TempDir()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	runs := []struct {
		key     string
		id      string
		display string
		project string
	}{
		{"run-20250731_170606-aaaaaaaa", "aaaaaaaa", "run-alpha", "proj-1"},
		{"run-20250731_170607-bbbbbbbb", "bbbbbbbb", "run-beta", "proj-1"},
		{"run-20250731_170608-cccccccc", "cccccccc", "run-gamma", "proj-2"},
	}

	for _, r := range runs {
		createRunWandbFile(t, wandbDir, r.key, []*spb.Record{
			{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
				RunId:       r.id,
				DisplayName: r.display,
				Project:     r.project,
			}}},
		})
	}

	w := leet.NewWorkspace(wandbDir, cfg, logger)

	// preload and update the workspace to populate the overview
	for _, r := range runs {
		msg := w.TestExecutePreloadCmd(r.key)
		require.NoError(t, msg.Err, "preload failed for %s", r.key)
		require.NotNil(t, msg.Run, "preload returned nil Run for %s", r.key)
		w.Update(msg)
	}

	for _, r := range runs {
		runOverview := w.TestGetRunOverviewByRunKey(r.key)
		require.Equal(t, r.id, runOverview.ID(),
			"overview ID mismatch for %s", r.key)
		require.Equal(t, r.display, runOverview.DisplayName(),
			"overview display name mismatch for %s", r.key)
		require.Equal(t, r.project, runOverview.Project(),
			"overview project mismatch for %s", r.key)
	}
}
