package leet

import (
	"errors"
	"fmt"
	"io"
	"os"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// LocalWorkspaceBackend discovers runs by polling the local filesystem
// and reads history from LevelDB-style .wandb transaction logs.
type LocalWorkspaceBackend struct {
	wandbDir string
	logger   *observability.CoreLogger
}

// NewLocalWorkspaceBackend creates a backend for a local wandb directory.
func NewLocalWorkspaceBackend(
	wandbDir string,
	logger *observability.CoreLogger,
) WorkspaceBackend {
	return &LocalWorkspaceBackend{
		wandbDir: wandbDir,
		logger:   logger,
	}
}

func (b *LocalWorkspaceBackend) DiscoverRunsCmd(delay time.Duration) tea.Cmd {
	wandbDir := b.wandbDir
	if delay < 0 {
		delay = 0
	}
	return tea.Tick(delay, func(time.Time) tea.Msg {
		runKeys, err := scanWandbRunDirs(wandbDir)
		return WorkspaceRunDiscoveryMsg{RunKeys: runKeys, Err: err}
	})
}

func (b *LocalWorkspaceBackend) NextDiscoveryCmd() tea.Cmd {
	return b.DiscoverRunsCmd(wandbDirPollInterval)
}

func (b *LocalWorkspaceBackend) InitReaderCmd(runKey string) tea.Cmd {
	// Resolve the run file before mutating selection state so we don't end up
	// "selected but unloadable" if the key can't be mapped to a .wandb file.
	wandbFile := runWandbFile(b.wandbDir, runKey)
	if wandbFile == "" {
		return nil
	}

	return func() tea.Msg {
		reader, err := NewLevelDBHistorySource(wandbFile, b.logger)
		if err != nil {
			return WorkspaceInitErrMsg{
				RunKey:  runKey,
				RunPath: wandbFile,
				Err:     err,
			}
		}
		return WorkspaceRunInitMsg{
			RunKey:  runKey,
			RunPath: wandbFile,
			Reader:  reader,
		}
	}
}

func (b *LocalWorkspaceBackend) PreloadOverviewCmd(runKey string) tea.Cmd {
	wandbFile := runWandbFile(b.wandbDir, runKey)
	logger := b.logger

	return func() tea.Msg {
		if runKey == "" || wandbFile == "" {
			return WorkspaceRunOverviewPreloadedMsg{
				RunKey: runKey, Err: errRunRecordNotFound}
		}

		reader, err := NewLevelDBHistorySource(wandbFile, logger)
		if err != nil {
			return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Err: err}
		}
		defer reader.Close()

		msg, err := reader.Read(maxRecordsToScan, maxRecordsToScanTimeout)
		if err != nil {
			if !errors.Is(err, io.EOF) {
				return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Err: err}
			}
		}
		if rm, ok := FindRunMsg(msg); ok {
			return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Run: &rm}
		}

		return WorkspaceRunOverviewPreloadedMsg{RunKey: runKey, Err: errRunRecordNotFound}
	}
}

func (b *LocalWorkspaceBackend) RunParams(runKey string) *RunParams {
	wandbFile := runWandbFile(b.wandbDir, runKey)
	if wandbFile == "" {
		return nil
	}
	return &RunParams{
		RunFile: wandbFile,
	}
}

func (b *LocalWorkspaceBackend) SeriesKey(runKey string) string {
	return runWandbFile(b.wandbDir, runKey)
}

func (b *LocalWorkspaceBackend) DisplayLabel() string {
	return b.wandbDir
}

// InitLiveUpdatesCmd implements WorkspaceBackend.InitLiveUpdatesCmd.
func (b *LocalWorkspaceBackend) InitLiveUpdatesCmd(w *Workspace) tea.Cmd {
	if w == nil || w.heartbeatMgr == nil || w.liveChan == nil {
		return nil
	}
	return w.waitForLiveMsg
}

// LiveUpdatesCmd implements WorkspaceBackend.LiveUpdatesCmd.
func (b *LocalWorkspaceBackend) LiveUpdatesCmd(
	w *Workspace,
	run *WorkspaceRun,
) tea.Cmd {
	if w == nil || run == nil || !run.state.mayBeLive() {
		return nil
	}

	var watcherCmd tea.Cmd
	if run.watcher == nil {
		ch := make(chan tea.Msg, 1) // coalesce notifications for this run
		run.watcher = NewWatcherManager(ch, w.logger)

		if err := run.watcher.Start(run.wandbPath); err != nil {
			w.logger.CaptureError(
				"leet",
				fmt.Errorf(
					"workspace: failed to start watcher for %s: %v",
					run.Key,
					err,
				),
			)
			run.watcher = nil
		} else {
			// Seed the staleness clock from the file so a run that died
			// before LEET started is caught on the first heartbeat rather
			// than a full RunCrashTimeout later.
			if info, err := os.Stat(run.wandbPath); err == nil {
				run.lastUpdateAt = info.ModTime()
			}
			watcherCmd = w.waitForWatcher(run.Key)
		}
	}

	w.syncLiveRunState()
	if w.heartbeatMgr != nil && w.hasLiveRuns.Load() {
		w.heartbeatMgr.Start(w.hasLiveRuns.Load)
	}

	return watcherCmd
}

// RunState implements WorkspaceBackend.RunState.
func (b *LocalWorkspaceBackend) RunState(
	w *Workspace,
	runKey string,
) RunState {
	state := w.runStateForKey(runKey)
	if state == RunStateRunning && w.runsByKey[runKey] == nil {
		// A local overview can be stale while its transaction log is no
		// longer being streamed.
		return RunStateUnknown
	}
	return state
}
