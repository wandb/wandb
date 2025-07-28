// Messages for the Bubble Tea model
package tui

import "time"

// HistoryMsg contains metrics data from a wandb history record.
type HistoryMsg struct {
	Metrics map[string]float64
	Step    int
}

// TickMsg represents a timer tick.
type TickMsg time.Time

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
