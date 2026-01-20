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
	Metrics map[string]MetricData
}

// RunMsg contains data from the wandb run record.
type RunMsg struct {
	ID          string
	Project     string
	DisplayName string
	Config      *spb.ConfigRecord
}

// SummaryMsg contains summary data from the wandb run.
type SummaryMsg struct {
	Summary []*spb.SummaryRecord
}

// SystemInfoMsg contains system/environment information.
type SystemInfoMsg struct {
	Record *spb.EnvironmentRecord
}

// FileChangedMsg indicates that the watched file has changed.
type FileChangedMsg struct{}

// FileCompleteMsg indicates that the file has been completely read.
type FileCompleteMsg struct {
	ExitCode int32
}

// StatsMsg contains system metrics data from a wandb stats record.
type StatsMsg struct {
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
