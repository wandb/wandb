// Messages for the Bubble Tea model
package observer

import (
	tea "github.com/charmbracelet/bubbletea"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// HistoryMsg contains metrics data from a wandb history record.
type HistoryMsg struct {
	Metrics map[string]float64
	Step    int
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
	Summary *spb.SummaryRecord
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

func (e ErrorMsg) Error() string {
	return e.Err.Error()
}

// InitMsg contains the initialized reader.
type InitMsg struct {
	Reader *WandbReader
}

// BatchedRecordsMsg contains all messages read during a batch read.
type BatchedRecordsMsg struct {
	Msgs []tea.Msg
}

// ReloadMsg indicates that the Run data should be reloaded
type ReloadMsg struct{}
