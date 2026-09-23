package leet

import (
	"time"

	tea "charm.land/bubbletea/v2"
)

// WorkspaceBackend encapsulates operations that differ between
// local (filesystem-based) and remote (GraphQL/parquet-based) workspaces.
//
// The Workspace struct handles all shared UI, rendering, state management,
// and message routing. It delegates backend-specific operations to this
// interface, avoiding duplication of the ~1800 lines of shared workspace logic.
type WorkspaceBackend interface {
	// DiscoverRunsCmd returns a command to discover available runs.
	// For local: polls the filesystem. For remote: queries GraphQL.
	// The returned command should produce a WorkspaceRunDiscoveryMsg.
	DiscoverRunsCmd(delay time.Duration) tea.Cmd

	// NextDiscoveryCmd returns a command to schedule the next discovery.
	// Returns nil if no discovery is needed.
	NextDiscoveryCmd() tea.Cmd

	// InitReaderCmd returns a command that creates a HistorySource
	// for the given run key. Produces a WorkspaceRunInitMsg on success
	// or a WorkspaceInitErrMsg on failure.
	InitReaderCmd(runKey string) tea.Cmd

	// PreloadOverviewCmd returns a command to preload run overview
	// metadata for an unselected run.
	PreloadOverviewCmd(runKey string) tea.Cmd

	// RunParams returns RunParams for entering single-run view.
	RunParams(runKey string) *RunParams

	// SeriesKey returns the identifier used for this run's series
	// in the metrics grid (for color mapping, pinning, removal).
	SeriesKey(runKey string) string

	// DisplayLabel returns the label shown in the status bar.
	DisplayLabel() string

	// InitLiveUpdatesCmd initializes backend-specific live update handling.
	InitLiveUpdatesCmd(workspace *Workspace) tea.Cmd

	// LiveUpdatesCmd starts backend-specific live updates for a run.
	LiveUpdatesCmd(workspace *Workspace, run *WorkspaceRun) tea.Cmd

	// RunState returns the state to display for a workspace run.
	RunState(workspace *Workspace, runKey string) RunState
}
