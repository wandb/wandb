//go:build !wandb_core

package leet

import (
	"context"
	"io"
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

// ReadAllData reads all available data and processes it.
func ReadAllData(reader *WandbReader) tea.Cmd {
	return func() tea.Msg {
		records, err := reader.ReadAllRecords()
		if err != nil {
			return ErrorMsg{Err: err}
		}

		ctx := context.Background()
		msgs, err := ProcessRecords(ctx, records)
		if err != nil {
			return ErrorMsg{Err: err}
		}

		return BatchedRecordsMsg{Msgs: msgs}
	}
}

// ReadAvailableRecords reads new records for live monitoring.
func ReadAvailableRecords(reader *WandbReader) tea.Cmd {
	return func() tea.Msg {
		var msgs []tea.Msg
		recordCount := 0
		const maxRecordsPerBatch = 100

		for recordCount < maxRecordsPerBatch {
			msg, err := reader.ReadNext()
			if err == io.EOF {
				// No more records available right now
				break
			}
			if err != nil {
				// Log error but continue
				continue
			}
			if msg != nil {
				msgs = append(msgs, msg)
				recordCount++
			}
		}

		if len(msgs) > 0 {
			return BatchedRecordsMsg{Msgs: msgs}
		}
		// No new records found
		return nil
	}
}

// AnimationDuration is the duration for sidebar animations
const AnimationDuration = 150 * time.Millisecond

// AnimationSteps is the number of steps in sidebar animations
const AnimationSteps = 10
