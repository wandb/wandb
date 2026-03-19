package leet

import (
	"errors"
	"io"
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
		if rm, ok := msg.(RunMsg); ok && rm.ID != "" {
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
		LocalRunParams: &LocalRunParams{
			RunFile: wandbFile,
		},
	}
}

func (b *LocalWorkspaceBackend) SeriesKey(runKey string) string {
	return runWandbFile(b.wandbDir, runKey)
}

func (b *LocalWorkspaceBackend) DisplayLabel() string {
	return b.wandbDir
}

func (b *LocalWorkspaceBackend) SupportsLiveStreaming() bool {
	return true
}
