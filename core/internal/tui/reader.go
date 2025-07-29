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
	store    *stream.Store
	exitSeen bool
}

// NewWandbReader creates a new wandb file reader.
func NewWandbReader(runPath string) (*WandbReader, error) {
	store := stream.NewStore(runPath)
	err := store.Open(os.O_RDONLY)
	if err != nil {
		return nil, err
	}
	return &WandbReader{
		store:    store,
		exitSeen: false,
	}, nil
}

// ReadNext reads the next record and converts it to a tea.Msg if relevant.
// It returns a nil message for records that are not handled by the UI.
func (r *WandbReader) ReadNext() (tea.Msg, error) {
	record, err := r.store.Read()
	if err != nil {
		if err == io.EOF && r.exitSeen {
			return FileCompleteMsg{}, io.EOF
		}
		return nil, err // Could be temporary EOF or another error
	}

	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		if rec.Run.Config != nil {
			return ConfigMsg{Record: rec.Run.Config}, nil
		}

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

	case *spb.Record_Summary:
		summaryMap := make(map[string]any)
		for _, item := range rec.Summary.Update {
			key := strings.Join(item.NestedKey, ".")
			summaryMap[key] = strings.Trim(item.ValueJson, `"`)
		}
		return SummaryMsg{Summary: summaryMap}, nil

	case *spb.Record_Environment:
		return SystemInfoMsg{Record: rec.Environment}, nil

	case *spb.Record_Exit:
		r.exitSeen = true
		return FileCompleteMsg{}, nil
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
