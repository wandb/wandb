// Messages for the Bubble Tea model
package tui

import (
	tea "github.com/charmbracelet/bubbletea"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// HistoryMsg contains metrics data from a wandb history record.
type HistoryMsg struct {
	Metrics map[string]float64
	Step    int
}

// ConfigMsg contains configuration data from the wandb run.
type ConfigMsg struct {
	Record *spb.ConfigRecord
}

// SummaryMsg contains summary data from the wandb run.
type SummaryMsg struct {
	Summary map[string]any
}

// SystemInfoMsg contains system/environment information.
type SystemInfoMsg struct {
	Record *spb.EnvironmentRecord
}

// FileChangedMsg indicates that the watched file has changed.
type FileChangedMsg struct{}

// FileCompleteMsg indicates that the file has been completely read.
type FileCompleteMsg struct{}

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

// InitialDataMsg contains all messages read during an initial or subsequent scan.
type InitialDataMsg struct {
	Msgs []tea.Msg
}
