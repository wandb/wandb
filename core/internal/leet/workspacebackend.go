package leet

import (
	"time"

	tea "charm.land/bubbletea/v2"
)

// WorkspaceBackend is where a workspace finds its runs: a local wandb
// directory or a remote W&B project.
type WorkspaceBackend interface {
	// DiscoverRunsCmd lists the runs after delay, producing a
	// WorkspaceRunDiscoveryMsg.
	DiscoverRunsCmd(delay time.Duration) tea.Cmd

	// NextDiscoveryCmd schedules the discovery that follows the last one.
	NextDiscoveryCmd() tea.Cmd

	// InitReaderCmd opens the run's history, producing a WorkspaceRunInitMsg
	// or a WorkspaceInitErrMsg. Returns nil if the run cannot be opened.
	InitReaderCmd(runKey string) tea.Cmd

	// PreloadOverviewCmd reads the metadata of a run that discovery listed
	// without it, producing a WorkspaceRunOverviewPreloadedMsg.
	PreloadOverviewCmd(runKey string) tea.Cmd

	// RunParams returns the parameters for opening the run in single-run view.
	RunParams(runKey string) *RunParams

	// SeriesKey identifies the run's series in the metrics grid.
	SeriesKey(runKey string) string

	// DisplayLabel names the runs being browsed in the status bar.
	DisplayLabel() string
}
