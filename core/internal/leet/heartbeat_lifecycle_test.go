package leet_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestRunHandleRecordMsg_DoesNotArmHeartbeatBeforeWatcherStarts(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	run := leet.NewRun("dummy", cfg, logger)

	_, _ = run.TestHandleRecordMsg(leet.RunMsg{ID: "run-1", DisplayName: "test"})
	_, _ = run.TestHandleRecordMsg(leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1}, Y: []float64{0.5}},
		},
	})

	require.False(t, run.TestHeartbeatTimerArmed())
}

func TestRunHandleRecordMsg_ArmsHeartbeatAfterWatcherStarts(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	run := leet.NewRun("dummy", cfg, logger)

	_, _ = run.TestHandleRecordMsg(leet.RunMsg{ID: "run-1", DisplayName: "test"})
	run.TestSetWatcherStarted(true)
	_, _ = run.TestHandleRecordMsg(leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1}, Y: []float64{0.5}},
		},
	})

	require.True(t, run.TestHeartbeatTimerArmed())
	run.TestStopHeartbeat()
}

func TestWorkspaceHandleWorkspaceRecord_DoesNotArmHeartbeatBeforeWatcherStarts(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	workspace := leet.NewWorkspace(t.TempDir(), cfg, logger)

	run := leet.TestNewWorkspaceRun("run-1")
	workspace.TestAttachRun(run, true)

	workspace.TestHandleWorkspaceRecord(run, leet.RunMsg{ID: "run-1", DisplayName: "test"})
	workspace.TestHandleWorkspaceRecord(run, leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1}, Y: []float64{0.5}},
		},
	})

	require.False(t, workspace.TestHeartbeatTimerArmed())
}

func TestWorkspaceHandleWorkspaceRecord_ArmsHeartbeatAfterWatcherStarts(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	workspace := leet.NewWorkspace(t.TempDir(), cfg, logger)

	run := leet.TestNewWorkspaceRun("run-1")
	run.TestSetWatcherStarted(true)
	workspace.TestAttachRun(run, true)

	workspace.TestHandleWorkspaceRecord(run, leet.RunMsg{ID: "run-1", DisplayName: "test"})
	workspace.TestHandleWorkspaceRecord(run, leet.HistoryMsg{
		Metrics: map[string]leet.MetricData{
			"loss": {X: []float64{1}, Y: []float64{0.5}},
		},
	})

	require.True(t, workspace.TestHeartbeatTimerArmed())
	workspace.TestStopHeartbeat()
}
