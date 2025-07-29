package tui

import (
	"context"
	"io"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/watcher" // Assuming local import path for your watcher
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

// ReadAvailableRecords reads all available records from the reader until a
// temporary EOF is reached.
func ReadAvailableRecords(reader *WandbReader) tea.Cmd {
	return func() tea.Msg {
		var msgs []tea.Msg
		for {
			msg, err := reader.ReadNext()
			if err != nil {
				if err == io.EOF {
					// Final EOF, run is complete.
					msgs = append(msgs, FileCompleteMsg{})
				}
				// For temporary EOF or other errors, we break and let the
				// watcher trigger the next read.
				break
			}
			if msg != nil {
				msgs = append(msgs, msg)
			}
		}

		if len(msgs) > 0 {
			return InitialDataMsg{Msgs: msgs}
		}
		return nil // No new messages, maybe a file flush
	}
}

// WatchFile creates a command that listens for file changes.
// It's a long-running command that sends a FileChangedMsg when the file is modified
// and can be cancelled via the provided context.
func WatchFile(w watcher.Watcher, path string, ctx context.Context) tea.Cmd {
	return func() tea.Msg {
		msgChan := make(chan tea.Msg, 1)

		// This goroutine runs the watcher's callback.
		go func() {
			onChange := func() {
				// Use a non-blocking send to avoid blocking the watcher goroutine
				// if the channel buffer is full.
				select {
				case msgChan <- FileChangedMsg{}:
				default:
				}
			}

			if err := w.Watch(path, onChange); err != nil {
				msgChan <- ErrorMsg{Err: err}
			}
		}()

		// This blocks until either a message is received from the watcher
		// or the context is cancelled.
		select {
		case msg := <-msgChan:
			return msg
		case <-ctx.Done():
			return nil // Command is cancelled
		}
	}
}
