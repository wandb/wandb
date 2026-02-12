package leet

import (
	"errors"
	"io"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

const (
	// Boot loading parameters
	BootLoadChunkSize = 1000
	BootLoadMaxTime   = 100 * time.Millisecond

	// Live monitoring parameters
	LiveMonitorChunkSize = 2000
	LiveMonitorMaxTime   = 50 * time.Millisecond
)

// HistorySource is an interface for reading W&B run history data.
//
// Implementations:
//   - LevelDBHistorySource: Reads from a LevelDB-style .wandb transaction log
//
// The Read method returns a ChunkedBatchMsg containing processed records,
// and may return io.EOF when the stream is complete.
type HistorySource interface {
	// Read reads events from the history source,
	// up to a given number of records or a given time period,
	// whichever is reached first.
	//
	// Returns a ChunkedBatchMsg with processed records and metadata.
	// If the history source has been completely read, it returns io.EOF error.
	Read(
		chunkSize int,
		maxTimePerChunk time.Duration,
	) (tea.Msg, error)

	// Close closes the history source that is being read from.
	Close()
}

// ReadAllRecordsChunked returns a command to read records in chunks for progressive loading.
func ReadAllRecordsChunked(source HistorySource) tea.Cmd {
	return func() tea.Msg {
		msgs, err := source.Read(
			BootLoadChunkSize,
			BootLoadMaxTime,
		)
		if err != nil && !errors.Is(err, io.EOF) {
			return ErrorMsg{Err: err}
		}
		return msgs
	}
}

// ReadAvailableRecords reads new records for live monitoring.
func ReadAvailableRecords(source HistorySource) tea.Cmd {
	return func() tea.Msg {
		msgs, err := source.Read(
			LiveMonitorChunkSize,
			LiveMonitorMaxTime,
		)

		// For live monitoring, we ignore EOF errors
		// since we may have more data to read later.
		if err != nil && !errors.Is(err, io.EOF) {
			return ErrorMsg{Err: err}
		}
		return msgs
	}
}
