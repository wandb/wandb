package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// InitializeReader creates a command to initialize the wandb reader.
func InitializeReader(runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewWandbReader(runPath)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InitMsg{Reader: reader}
	}
}

// ReadAllDataOptimized creates a command to read all data using bulk processing
func ReadAllDataOptimized(reader *WandbReader) tea.Cmd {
	return func() tea.Msg {
		data, err := reader.ReadAllDataOptimized()
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return BulkDataMsg{Data: data}
	}
}

// ReadAvailableRecords reads all available records from the reader until a
// temporary EOF is reached. Used for live monitoring.
func ReadAvailableRecords(reader *WandbReader) tea.Cmd {
	return func() tea.Msg {
		var msgs []tea.Msg
		for {
			msg, err := reader.ReadNext()
			if msg != nil {
				msgs = append(msgs, msg)
			}
			if err != nil {
				break
			}
		}

		if len(msgs) > 0 {
			return BatchedRecordsMsg{Msgs: msgs}
		}
		return nil
	}
}

// AnimationDuration is the duration for sidebar animations
const AnimationDuration = 150 * time.Millisecond

// AnimationSteps is the number of steps in sidebar animations
const AnimationSteps = 10
