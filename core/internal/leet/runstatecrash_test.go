package leet_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func newLiveRunForCrashTest(t *testing.T) *leet.Run {
	t.Helper()

	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	run := leet.NewRun(&leet.RunParams{RunFile: "dummy"}, cfg, logger)
	run.TestHandleRecordMsg(leet.RunMsg{ID: "run-1", DisplayName: "test"})
	require.Equal(t, leet.RunStateRunning, run.TestRunState())
	return run
}

func TestRunFileComplete_ExitCode254MapsToCrashed(t *testing.T) {
	run := newLiveRunForCrashTest(t)

	run.TestHandleRecordMsg(leet.FileCompleteMsg{ExitCode: 254})

	require.Equal(t, leet.RunStateCrashed, run.TestRunState())
}
