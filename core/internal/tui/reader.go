package tui

import (
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
	store := stream.NewStore(runPath)
	err := store.Open(os.O_RDONLY)
	if err != nil {
		return nil, err
	}

	// Initialize with the current offset (should be after header)
	initialOffset := store.GetCurrentOffset()

	return &WandbReader{
		store:          store,
		exitSeen:       false,
		lastGoodOffset: initialOffset,
	}, nil
}

// ReadNext reads the next record and converts it to a tea.Msg if relevant.
// It returns a nil message for records that are not handled by the UI.
//
//gocyclo:ignore
func (r *WandbReader) ReadNext() (tea.Msg, error) {
	// Save current position before attempting read
	currentOffset := r.store.GetCurrentOffset()

	record, err := r.store.Read()
	if err != nil {
		if err == io.EOF {
			if r.exitSeen {
				return FileCompleteMsg{ExitCode: r.exitCode}, io.EOF
			}

			// For live runs with EOF, seek back to last known good position
			// This prevents skipping incomplete records when new data arrives
			if r.lastGoodOffset >= 0 && currentOffset >= 0 {
				if seekErr := r.store.SeekToOffset(r.lastGoodOffset); seekErr == nil {
					// Successfully seeked back, don't call Recover()
					return nil, err
				}
			}

			// Fallback to recover if seek fails or offsets unavailable
			r.store.Recover()
		} else {
			// For non-EOF errors, try seeking back first
			if r.lastGoodOffset >= 0 && currentOffset >= 0 {
				if seekErr := r.store.SeekToOffset(r.lastGoodOffset); seekErr != nil {
					// If seek fails, use recover as fallback
					r.store.Recover()
				}
			} else {
				r.store.Recover()
			}
		}
		return nil, err
	}

	// Successfully read a record - update our last good position
	if currentOffset >= 0 {
		r.lastGoodOffset = currentOffset
	}

	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		return RunMsg{
			ID:          rec.Run.RunId,
			DisplayName: rec.Run.DisplayName,
			Project:     rec.Run.Project,
			Config:      rec.Run.Config,
		}, nil

	case *spb.Record_History:
		metrics := make(map[string]float64)
		var step int

		for _, item := range rec.History.Item {
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

			valueStr := strings.Trim(item.ValueJson, `"`)
			if value, err := strconv.ParseFloat(valueStr, 64); err == nil {
				metrics[key] = value
			}
		}

		if len(metrics) > 0 {
			return HistoryMsg{Metrics: metrics, Step: step}, nil
		}

	case *spb.Record_Stats:
		metrics := make(map[string]float64)
		var timestamp int64

		if rec.Stats.Timestamp != nil {
			timestamp = rec.Stats.Timestamp.Seconds
		}

		for _, item := range rec.Stats.Item {
			key := item.Key
			valueStr := strings.Trim(item.ValueJson, `"`)
			if value, err := strconv.ParseFloat(valueStr, 64); err == nil {
				metrics[key] = value
			}
		}

		if len(metrics) > 0 {
			return StatsMsg{Timestamp: timestamp, Metrics: metrics}, nil
		}

	case *spb.Record_Summary:
		return SummaryMsg{Summary: rec.Summary}, nil

	case *spb.Record_Environment:
		return SystemInfoMsg{Record: rec.Environment}, nil

	case *spb.Record_Exit:
		r.exitSeen = true
		r.exitCode = rec.Exit.ExitCode
		return FileCompleteMsg{ExitCode: r.exitCode}, nil
	}

	// Return nil for unhandled record types
	return nil, nil
}

// Close closes the reader.
func (r *WandbReader) Close() error {
	if r.store != nil {
		return r.store.Close()
	}
	return nil
}
