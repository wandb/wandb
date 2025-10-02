package leet

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// WandbReader handles reading records from a W&B LevelDB-style transaction log (.wandb file).
type WandbReader struct {
	// store is a W&B LevelDB-style transaction log that may be actively written.
	store *LiveStore
	// exitSeen indicates whether an ExitRecord has been seen.
	exitSeen bool
	// exitCode is the ext code reported in the ExitRecord (if seen).
	exitCode int32
}

// NewWandbReader creates a new wandb file reader.
func NewWandbReader(runPath string, logger *observability.CoreLogger) (*WandbReader, error) {
	_, err := os.Stat(runPath)
	if os.IsNotExist(err) {
		return nil, fmt.Errorf("reader: wandb file not found: %s", runPath)
	}

	store, err := NewLiveStore(runPath, logger)
	if err != nil {
		return nil, fmt.Errorf("reader: failed to create live store: %v", err)
	}

	return &WandbReader{store: store}, nil
}

// ReadAllRecordsChunked reads all available records in chunks
// and forwards them for processing as batches.
func (r *WandbReader) ReadAllRecordsChunked() tea.Msg {
	if r == nil {
		// No reader available; no-op to keep Bubble Tea flow consistent.
		return func() tea.Msg { return nil }
	}
	const chunkSize = 1000
	const maxTimePerChunk = 50 * time.Millisecond

	if r.store == nil {
		return ChunkedBatchMsg{Msgs: []tea.Msg{}, HasMore: false}
	}

	var msgs []tea.Msg
	recordCount := 0
	startTime := time.Now()
	hitEOF := false

	for recordCount < chunkSize && time.Since(startTime) < maxTimePerChunk {
		record, err := r.store.Read()
		if err != nil {
			break
		}

		if record == nil {
			continue
		}
		// Handle exit record first to avoid double FileComplete
		if exit, ok := record.RecordType.(*spb.Record_Exit); ok && exit.Exit != nil {
			r.exitSeen = true
			r.exitCode = exit.Exit.ExitCode
			msgs = append(msgs, FileCompleteMsg{ExitCode: r.exitCode})
			hitEOF = true // Treat as EOF
			break
		}
		// Non-exit record: convert and append
		if msg := r.recordToMsg(record); msg != nil {
			msgs = append(msgs, msg)
			recordCount++
		}
	}

	// Determine if there's more to read,
	// i.e. whether we have records and didn't hit EOF, there might be more.
	hasMore := !r.exitSeen && !hitEOF && recordCount > 0

	return ChunkedBatchMsg{
		Msgs:     msgs,
		HasMore:  hasMore,
		Progress: recordCount,
	}
}

func (reader *WandbReader) ReadAvailableRecords() tea.Msg {
	// No reader? Nothing to do.
	if reader == nil {
		return func() tea.Msg { return nil }
	}

	var msgs []tea.Msg
	recordCount := 0

	// Read more per batch, but keep a small time budget to stay responsive.
	const maxRecordsPerBatch = 2000
	const maxBatchTime = 50 * time.Millisecond
	start := time.Now()

	for recordCount < maxRecordsPerBatch && time.Since(start) < maxBatchTime {
		msg, err := reader.ReadNext()
		if err == io.EOF {
			// No more records available right now.
			break
		}
		if err != nil {
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
	// No new records found.
	return nil

}

// ReadNext reads the next record for live monitoring.
func (r *WandbReader) ReadNext() (tea.Msg, error) {
	if r == nil || r.store == nil {
		return nil, io.EOF
	}

	record, err := r.store.Read()

	if err != nil && err != io.EOF {
		return nil, err
	}

	if err == io.EOF {
		if r.exitSeen {
			return FileCompleteMsg{ExitCode: r.exitCode}, io.EOF
		}
		// We hit EOF, but the run isn't finished yet.
		return nil, io.EOF
	}

	return r.recordToMsg(record), nil
}

// recordToMsg converts a record to the appropriate message type.
func (r *WandbReader) recordToMsg(record *spb.Record) tea.Msg {
	switch rec := record.RecordType.(type) {
	case *spb.Record_Exit:
		r.exitSeen = true
		r.exitCode = rec.Exit.GetExitCode()
		return FileCompleteMsg{ExitCode: r.exitCode}

	case *spb.Record_Run:
		return RunMsg{
			ID:          rec.Run.GetRunId(),
			DisplayName: rec.Run.GetDisplayName(),
			Project:     rec.Run.GetProject(),
			Config:      rec.Run.GetConfig(),
		}
	case *spb.Record_History:
		return ParseHistory(rec.History)
	case *spb.Record_Stats:
		return ParseStats(rec.Stats)
	case *spb.Record_Summary:
		return SummaryMsg{Summary: rec.Summary}
	case *spb.Record_Environment:
		return SystemInfoMsg{Record: rec.Environment}
	default:
		return nil
	}
}

// ParseHistory extracts metrics from a history record.
func ParseHistory(history *spb.HistoryRecord) tea.Msg {
	metrics := make(map[string]float64)
	var step int

	for _, item := range history.GetItem() {
		key := strings.Join(item.GetNestedKey(), ".")
		if key == "" {
			key = item.GetKey()
		}
		if key == "" {
			continue
		}

		if key == "_step" {
			if val, err := strconv.Atoi(strings.Trim(item.ValueJson, `"`)); err == nil {
				step = val
			}
			continue
		}

		if strings.HasPrefix(key, "_") {
			continue
		}

		if value, err := strconv.ParseFloat(strings.Trim(item.ValueJson, `"`), 64); err == nil {
			metrics[key] = value
		}
	}

	if len(metrics) > 0 {
		return HistoryMsg{Metrics: metrics, Step: step}
	}
	return nil
}

// ParseStats extracts metrics from a stats record.
func ParseStats(stats *spb.StatsRecord) tea.Msg {
	if stats == nil {
		return nil
	}

	metrics := make(map[string]float64)
	var timestamp int64

	if stats.Timestamp != nil {
		timestamp = stats.Timestamp.Seconds
	}

	for _, item := range stats.Item {
		if item == nil {
			continue
		}

		if value, err := strconv.ParseFloat(strings.Trim(item.ValueJson, `"`), 64); err == nil {
			metrics[item.Key] = value
		}
	}

	if len(metrics) > 0 {
		return StatsMsg{Timestamp: timestamp, Metrics: metrics}
	}
	return nil
}

// Close closes the reader.
func (r *WandbReader) Close() {
	if r.store != nil {
		r.store.Close()
	}
}

// InitializeReader creates a command to initialize the wandb reader.
func InitializeReader(runPath string, logger *observability.CoreLogger) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewWandbReader(runPath, logger)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InitMsg{Reader: reader}
	}
}

// ReadAllRecordsChunked returns a command to read records in chunks for progressive loading.
func ReadAllRecordsChunked(reader *WandbReader) tea.Cmd {
	return reader.ReadAllRecordsChunked
}

// ReadAvailableRecords reads new records for live monitoring.
func ReadAvailableRecords(reader *WandbReader) tea.Cmd {
	return reader.ReadAvailableRecords
}
