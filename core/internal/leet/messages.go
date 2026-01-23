package leet

import (
	tea "github.com/charmbracelet/bubbletea"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type MetricData struct {
	X []float64
	Y []float64
}

// HistoryMsg contains metrics data from a wandb history record.
type HistoryMsg struct {
	RunPath string
	Metrics map[string]MetricData
}

// RunMsg contains data from the wandb run record.
type RunMsg struct {
	RunPath     string
	ID          string
	Project     string
	DisplayName string
	Config      *spb.ConfigRecord
}

// SummaryMsg contains summary data from the wandb run.
type SummaryMsg struct {
	RunPath string
	Summary []*spb.SummaryRecord
}

// SystemInfoMsg contains system/environment information.
type SystemInfoMsg struct {
	RunPath string
	Record  *spb.EnvironmentRecord
}

// FileChangedMsg indicates that the watched file has changed.
type FileChangedMsg struct{}

// FileCompleteMsg indicates that the file has been completely read.
type FileCompleteMsg struct {
	ExitCode int32
}

// StatsMsg contains system metrics data from a wandb stats record.
type StatsMsg struct {
	RunPath   string
	Timestamp int64              // Unix timestamp in seconds
	Metrics   map[string]float64 // metric name -> value
}

// ErrorMsg wraps an error.
type ErrorMsg struct {
	Err error
}

// InitMsg contains the initialized reader.
type InitMsg struct {
	Reader *WandbReader
}

// BatchedRecordsMsg contains all messages read during a batch read.
type BatchedRecordsMsg struct {
	Msgs []tea.Msg
}

// ChunkedBatchMsg contains a chunk of messages with progress info.
type ChunkedBatchMsg struct {
	Msgs []tea.Msg
	// Indicates if there are more chunks to read
	HasMore bool
	// Number of records in this chunk
	Progress int
}

// HeartbeatMsg is sent periodically for live runs to ensure we don't miss data.
type HeartbeatMsg struct{}

// LeftSidebarAnimationMsg is sent during left sidebar animations.
type LeftSidebarAnimationMsg struct{}

// RightSidebarAnimationMsg is sent during right sidebar animations.
type RightSidebarAnimationMsg struct{}

// WorkspaceRunsAnimationMsg drives animation for the workspace left sidebar.
type WorkspaceRunsAnimationMsg struct{}

// WorkspaceOverviewAnimationMsg drives animation for the workspace right sidebar.
type WorkspaceRunOverviewAnimationMsg struct{}

// WorkspaceInitMsg is emitted when a workspace run reader has been initialized.
type WorkspaceInitMsg struct {
	RunKey  string
	RunPath string
	Reader  *WandbReader
}

// WorkspaceChunkedBatchMsg wraps a ChunkedBatchMsg with the originating run key.
type WorkspaceChunkedBatchMsg struct {
	RunKey string
	Batch  ChunkedBatchMsg
}

// WorkspaceBatchedRecordsMsg wraps a BatchedRecordsMsg with the originating run key.
type WorkspaceBatchedRecordsMsg struct {
	RunKey string
	Batch  BatchedRecordsMsg
}

// WorkspaceFileChangedMsg is emitted when a watched workspace run's .wandb
// file changes on disk.
//
// It carries the run key so the workspace can refresh just that run.
type WorkspaceFileChangedMsg struct {
	RunKey string
}

// WorkspaceRunDirsMsg is emitted after polling the wandb directory.
//
// RunKeys contains the set of run directory names (e.g. "run-..." / "offline-run-...").
// If Err is non-nil, RunKeys may be nil and callers should treat the snapshot
// as unusable.
type WorkspaceRunDirsMsg struct {
	RunKeys []string
	Err     error
}
