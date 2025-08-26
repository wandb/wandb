//go:build !wandb_core

package leet

import (
	"context"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// WandbReader handles reading records from a .wandb file.
type WandbReader struct {
	store          *stream.Store
	exitSeen       bool
	exitCode       int32
	lastGoodOffset int64
	filepath       string
}

// NewWandbReader creates a new wandb file reader.
func NewWandbReader(runPath string) (*WandbReader, error) {
	// Check if file exists
	info, err := os.Stat(runPath)
	if os.IsNotExist(err) {
		return nil, fmt.Errorf("wandb file not found: %s", runPath)
	}

	store := stream.NewStore(runPath)

	reader := &WandbReader{
		store:          store,
		filepath:       runPath,
		exitSeen:       false,
		lastGoodOffset: 0,
	}

	// Check if file is too small for header (7 bytes minimum)
	if info.Size() < 7 {
		// File is too small, but might grow later (for live monitoring)
		return reader, nil
	}

	// Try to open the store for reading
	err = store.Open(os.O_RDONLY)
	if err != nil {
		// If the error is about header verification, the file might be incomplete
		if strings.Contains(err.Error(), "VerifyWandbHeader") ||
			strings.Contains(err.Error(), "invalid W&B") ||
			strings.Contains(err.Error(), "EOF") {
			// File exists but header is not valid yet
			// Close the store and we'll retry later
			store.Close()
			reader.store = nil
			return reader, nil
		}
		return nil, fmt.Errorf("failed to open store: %w", err)
	}

	// Get initial offset after header (should be 7 for W&B files)
	initialOffset := store.GetCurrentOffset()
	if initialOffset > 0 {
		reader.lastGoodOffset = initialOffset
	} else {
		reader.lastGoodOffset = 7 // Default to after header
	}

	return reader, nil
}

// tryReopenStore attempts to reopen the store if it's not open
func (r *WandbReader) tryReopenStore() error {
	if r.store != nil {
		return nil // Already open
	}

	// Check if file now has enough bytes for header
	info, err := os.Stat(r.filepath)
	if err != nil {
		return err
	}

	if info.Size() < 7 {
		return fmt.Errorf("file too small for header")
	}

	// Create new store if needed
	if r.store == nil {
		r.store = stream.NewStore(r.filepath)
	}

	// Try to open the store
	err = r.store.Open(os.O_RDONLY)
	if err != nil {
		return err
	}

	// Reset to last known good position if we have one
	if r.lastGoodOffset > 0 {
		_ = r.store.SeekToOffset(r.lastGoodOffset)
	} else {
		r.lastGoodOffset = r.store.GetCurrentOffset()
		if r.lastGoodOffset < 0 {
			r.lastGoodOffset = 7 // Default to after header
		}
	}

	return nil
}

// ReadAllRecordsChunked reads all available records in chunks and sends them as batches
func (r *WandbReader) ReadAllRecordsChunked() tea.Cmd {
	return func() tea.Msg {
		const chunkSize = 100                          // Process records in chunks
		const maxTimePerChunk = 100 * time.Millisecond // Increased time limit

		// Try to open store if not already open
		if err := r.tryReopenStore(); err != nil {
			// If we can't open the store yet, return empty batch
			return ChunkedBatchMsg{Msgs: []tea.Msg{}, HasMore: false}
		}

		if r.store == nil {
			return ChunkedBatchMsg{Msgs: []tea.Msg{}, HasMore: false}
		}

		var msgs []tea.Msg
		recordCount := 0
		startTime := time.Now()
		hitEOF := false

		for recordCount < chunkSize && time.Since(startTime) < maxTimePerChunk {
			// Save position before attempting read
			currentPos := r.store.GetCurrentOffset()

			record, err := r.store.Read()

			if err == io.EOF {
				// Update last good offset to current position
				if currentPos > 0 {
					r.lastGoodOffset = currentPos
				}
				hitEOF = true
				break
			}

			if err != nil {
				// Error reading record - it might be incomplete
				// Recover and try to continue from next block
				r.store.Recover()

				// Try one more read after recovery
				record, err = r.store.Read()
				if err != nil {
					// Still failing, update last good position and break
					if currentPos > 0 && currentPos > r.lastGoodOffset {
						r.lastGoodOffset = currentPos
					}
					// Don't continue, might be corrupted
					break
				}
			}

			if record != nil {
				if msg := recordToMsg(record); msg != nil {
					msgs = append(msgs, msg)
					recordCount++
				}

				// Update last good offset after successful read
				newPos := r.store.GetCurrentOffset()
				if newPos > 0 {
					r.lastGoodOffset = newPos
				}

				// Check for exit record
				if exit, ok := record.RecordType.(*spb.Record_Exit); ok {
					r.exitSeen = true
					r.exitCode = exit.Exit.ExitCode
					msgs = append(msgs, FileCompleteMsg{ExitCode: r.exitCode})
					hitEOF = true // Treat as EOF
					break
				}
			}
		}

		// Determine if there's more to read
		hasMore := false
		if !r.exitSeen && !hitEOF && recordCount > 0 {
			// We have records and didn't hit EOF, there might be more
			hasMore = true
		}

		return ChunkedBatchMsg{
			Msgs:     msgs,
			HasMore:  hasMore,
			Progress: recordCount,
		}
	}
}

// ReadAllRecords reads all available records from the file.
func (r *WandbReader) ReadAllRecords() ([]*spb.Record, error) {
	var records []*spb.Record

	// Try to open store if not already open
	if err := r.tryReopenStore(); err != nil {
		// If we can't open the store, return empty records
		return records, nil
	}

	if r.store == nil {
		return records, nil
	}

	for {
		// Save position before attempting read
		currentPos := r.store.GetCurrentOffset()

		record, err := r.store.Read()

		if err == io.EOF {
			// Update last good offset to current position
			if currentPos > 0 {
				r.lastGoodOffset = currentPos
			}
			break
		}

		if err != nil {
			// Error reading record - it might be incomplete
			// Recover and try to continue from next block
			r.store.Recover()

			// Try one more read after recovery
			record, err = r.store.Read()
			if err != nil {
				// Still failing, update last good position and continue
				if currentPos > 0 && currentPos > r.lastGoodOffset {
					r.lastGoodOffset = currentPos
				}
				continue
			}
		}

		if record != nil {
			records = append(records, record)

			// Update last good offset after successful read
			newPos := r.store.GetCurrentOffset()
			if newPos > 0 {
				r.lastGoodOffset = newPos
			}

			// Check for exit record
			if exit, ok := record.RecordType.(*spb.Record_Exit); ok {
				r.exitSeen = true
				r.exitCode = exit.Exit.ExitCode
			}
		}
	}

	return records, nil
}

// ReadNext reads the next record for live monitoring.
func (r *WandbReader) ReadNext() (tea.Msg, error) {
	// Try to open store if not already open (for files that are being written)
	if err := r.tryReopenStore(); err != nil {
		return nil, io.EOF
	}

	if r.store == nil {
		return nil, io.EOF
	}

	// Save position before attempting read
	beforeReadOffset := r.store.GetCurrentOffset()
	if beforeReadOffset < 0 {
		beforeReadOffset = r.lastGoodOffset
	}

	// Try to read the next record
	record, err := r.store.Read()

	if err == io.EOF && !r.exitSeen {
		// We hit EOF, but the run isn't finished yet
		// Seek back to last known good position and wait for more data
		if r.lastGoodOffset > 0 {
			if seekErr := r.store.SeekToOffset(r.lastGoodOffset); seekErr != nil {
				// If seek fails, try to recover
				r.store.Recover()
			}
		}
		return nil, io.EOF
	}

	if err != nil && err != io.EOF {
		// Error reading - might be incomplete record in live file
		// Try to recover by seeking back to before this read attempt
		if beforeReadOffset > 0 {
			if seekErr := r.store.SeekToOffset(beforeReadOffset); seekErr == nil {
				// Successfully seeked back, try reading again
				record, err = r.store.Read()
				if err != nil {
					// Still failing, seek to last known good
					if r.lastGoodOffset > 0 && r.lastGoodOffset < beforeReadOffset {
						_ = r.store.SeekToOffset(r.lastGoodOffset)
					}
					return nil, err
				}
			} else {
				// Seek failed, try recover
				r.store.Recover()
				return nil, err
			}
		} else {
			// No valid offset to seek back to
			r.store.Recover()
			return nil, err
		}
	}

	if err == io.EOF {
		if r.exitSeen {
			return FileCompleteMsg{ExitCode: r.exitCode}, io.EOF
		}
		return nil, io.EOF
	}

	// Successfully read a record
	afterReadOffset := r.store.GetCurrentOffset()
	if afterReadOffset > 0 {
		r.lastGoodOffset = afterReadOffset
	}

	// Check if this is an exit record
	if exit, ok := record.RecordType.(*spb.Record_Exit); ok {
		r.exitSeen = true
		r.exitCode = exit.Exit.ExitCode
		return FileCompleteMsg{ExitCode: r.exitCode}, nil
	}

	return recordToMsg(record), nil
}

// ProcessRecords processes a batch of records and returns messages.
func ProcessRecords(ctx context.Context, records []*spb.Record) ([]tea.Msg, error) {
	var msgs []tea.Msg

	for _, record := range records {
		if msg := recordToMsg(record); msg != nil {
			msgs = append(msgs, msg)
		}
	}

	return msgs, nil
}

// recordToMsg converts a record to the appropriate message type.
func recordToMsg(record *spb.Record) tea.Msg {
	if record == nil {
		return nil
	}

	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		if rec.Run != nil {
			return RunMsg{
				ID:          rec.Run.RunId,
				DisplayName: rec.Run.DisplayName,
				Project:     rec.Run.Project,
				Config:      rec.Run.Config,
			}
		}
	case *spb.Record_History:
		if rec.History != nil {
			return parseHistory(rec.History)
		}
	case *spb.Record_Stats:
		if rec.Stats != nil {
			return parseStats(rec.Stats)
		}
	case *spb.Record_Summary:
		if rec.Summary != nil {
			return SummaryMsg{Summary: rec.Summary}
		}
	case *spb.Record_Environment:
		if rec.Environment != nil {
			return SystemInfoMsg{Record: rec.Environment}
		}
	case *spb.Record_Exit:
		if rec.Exit != nil {
			return FileCompleteMsg{ExitCode: rec.Exit.ExitCode}
		}
	}
	return nil
}

// parseHistory extracts metrics from a history record.
func parseHistory(history *spb.HistoryRecord) tea.Msg {
	if history == nil {
		return nil
	}

	metrics := make(map[string]float64)
	var step int

	for _, item := range history.Item {
		if item == nil {
			continue
		}

		key := strings.Join(item.NestedKey, ".")
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

// parseStats extracts metrics from a stats record.
func parseStats(stats *spb.StatsRecord) tea.Msg {
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
func (r *WandbReader) Close() error {
	if r == nil {
		return nil
	}
	if r.store != nil {
		return r.store.Close()
	}
	return nil
}
