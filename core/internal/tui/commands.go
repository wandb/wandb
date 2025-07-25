package tui

import (
	"io"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// InitializeReader creates a command to initialize the wandb reader
func InitializeReader(runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewWandbReader(runPath)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InitMsg{Reader: reader}
	}
}

// ReadNextHistoryRecord creates a command to read the next history record
func ReadNextHistoryRecord(reader *WandbReader) tea.Cmd {
	return func() tea.Msg {
		metrics, step, err := reader.ReadNext()
		if err == io.EOF {
			return FileCompleteMsg{}
		}
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return HistoryMsg{Metrics: metrics, Step: step}
	}
}

// TickCmd creates a command for periodic ticking
func TickCmd() tea.Cmd {
	return tea.Tick(100*time.Millisecond, func(t time.Time) tea.Msg {
		return TickMsg(t)
	})
}
