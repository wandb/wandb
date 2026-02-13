package leet

import (
	"errors"
	"io"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
//   - ParquetHistorySource: Reads from a run's exported parquet history files.
//     The files are downloaded from the W&B backend.
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

// ReadRecords returns a command to read te given number of records for the given time period.
func ReadRecords(
	source HistorySource,
	chunkSize int,
	maxTimePerChunk time.Duration,
) tea.Cmd {
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

func concatenateHistory(messages []HistoryMsg, runPath string) HistoryMsg {
	h := HistoryMsg{
		RunPath: runPath,
		Metrics: make(map[string]MetricData),
	}
	for _, msg := range messages {
		for metricName, data := range msg.Metrics {
			existing := h.Metrics[metricName]
			existing.X = append(existing.X, data.X...)
			existing.Y = append(existing.Y, data.Y...)
			h.Metrics[metricName] = existing
		}
	}
	return h
}

func concatenateSummary(messages []SummaryMsg, runPath string) SummaryMsg {
	s := SummaryMsg{
		RunPath: runPath,
		Summary: make([]*spb.SummaryRecord, 0),
	}
	for _, msg := range messages {
		s.Summary = append(s.Summary, msg.Summary...)
	}
	return s
}
