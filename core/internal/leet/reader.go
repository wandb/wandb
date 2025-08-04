package leet

import (
	"context"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

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
}

// NewWandbReader creates a new wandb file reader.
func NewWandbReader(runPath string) (*WandbReader, error) {
	// Check if file exists
	if _, err := os.Stat(runPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("wandb file not found: %s", runPath)
	}

	store := stream.NewStore(runPath)
	err := store.Open(os.O_RDONLY)

	// If we get a header EOF error, the file exists but is empty - that's OK
	if err != nil && !strings.Contains(err.Error(), "failed to read header: EOF") {
		return nil, err
	}

	initialOffset := store.GetCurrentOffset()
	if initialOffset < 0 {
		initialOffset = 0
	}

	return &WandbReader{
		store:          store,
		exitSeen:       false,
		lastGoodOffset: initialOffset,
	}, nil
}

// ReadAllRecords reads all available records from the file.
func (r *WandbReader) ReadAllRecords() ([]*spb.Record, error) {
	var records []*spb.Record

	for {
		record, err := r.store.Read()

		if err == io.EOF {
			r.lastGoodOffset = r.store.GetCurrentOffset()
			if r.lastGoodOffset < 0 {
				r.lastGoodOffset = 0
			}
			break
		}

		if err != nil {
			// Empty file with no header yet - that's OK
			if strings.Contains(err.Error(), "failed to read header: EOF") {
				r.lastGoodOffset = 0
				break
			}
			continue
		}

		if record != nil {
			records = append(records, record)

			currentOffset := r.store.GetCurrentOffset()
			if currentOffset > 0 {
				r.lastGoodOffset = currentOffset
			}

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
	// Always try to read first
	record, err := r.store.Read()

	if err == io.EOF && !r.exitSeen {
		// We hit EOF, but the run isn't finished yet
		// Seek back to where we last successfully read
		if err := r.store.SeekToOffset(r.lastGoodOffset); err != nil {
			r.store.Recover()
		}
		// Try reading again after seeking
		record, err = r.store.Read()
	}

	if err != nil {
		if err == io.EOF {
			// Still EOF after seeking, we're truly at the end for now
			if r.exitSeen {
				return FileCompleteMsg{ExitCode: r.exitCode}, io.EOF
			}
			return nil, err
		}
		// Other errors
		r.store.Recover()
		return nil, err
	}

	// Successfully read a record
	// Update our position to after this record
	currentOffset := r.store.GetCurrentOffset()
	if currentOffset > 0 {
		r.lastGoodOffset = currentOffset
	}

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
	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		return RunMsg{
			ID:          rec.Run.RunId,
			DisplayName: rec.Run.DisplayName,
			Project:     rec.Run.Project,
			Config:      rec.Run.Config,
		}
	case *spb.Record_History:
		return parseHistory(rec.History)
	case *spb.Record_Stats:
		return parseStats(rec.Stats)
	case *spb.Record_Summary:
		return SummaryMsg{Summary: rec.Summary}
	case *spb.Record_Environment:
		return SystemInfoMsg{Record: rec.Environment}
	case *spb.Record_Exit:
		return FileCompleteMsg{ExitCode: rec.Exit.ExitCode}
	}
	return nil
}

// parseHistory extracts metrics from a history record.
func parseHistory(history *spb.HistoryRecord) tea.Msg {
	metrics := make(map[string]float64)
	var step int

	for _, item := range history.Item {
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
	metrics := make(map[string]float64)
	var timestamp int64

	if stats.Timestamp != nil {
		timestamp = stats.Timestamp.Seconds
	}

	for _, item := range stats.Item {
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
	if r.store != nil {
		return r.store.Close()
	}
	return nil
}
