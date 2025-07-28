package tui

import (
	"io"
	"os"
	"strconv"
	"strings"

	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// WandbReader handles reading from the .wandb file.
type WandbReader struct {
	store       *stream.Store
	config      *runconfig.RunConfig
	environment *runenvironment.RunEnvironment
	// TODO: summary
	exitSeen bool
}

// NewWandbReader creates a new wandb file reader
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

// Next reads the next history record from the .wandb file.
func (r *WandbReader) Next() (map[string]float64, int, error) {
	for {
		record, err := r.store.Read()
		if err == io.EOF && r.exitSeen {
			return nil, 0, io.EOF
		}
		if err != nil {
			return nil, 0, err
		}

		switch rec := record.RecordType.(type) {
		case *spb.Record_Environment:
			if r.environment == nil {
				r.environment = runenvironment.New(rec.Environment.WriterId)
			}
			r.environment.ProcessRecord(rec.Environment)

		case *spb.Record_Run:
			if r.config == nil {
				r.config = runconfig.New()
			}
			if rec.Run.Config != nil {
				r.config.ApplyChangeRecord(rec.Run.Config, nil)
			}

		case *spb.Record_History:
			// Extract metrics from history record
			metrics := make(map[string]float64)
			step := 0

			for _, item := range rec.History.Item {
				key := strings.Join(item.NestedKey, ".")

				// Parse step value
				if key == "_step" {
					if val, err := strconv.Atoi(strings.Trim(item.ValueJson, "\"")); err == nil {
						step = val
					}
				}

				// Skip underscored metrics.
				if strings.HasPrefix(key, "_") {
					continue
				}

				// Parse numeric values
				valueStr := strings.Trim(item.ValueJson, "\"")
				if value, err := strconv.ParseFloat(valueStr, 64); err == nil {
					metrics[key] = value
				}
			}

			if len(metrics) > 0 {
				return metrics, step, nil
			}

		case *spb.Record_Exit:
			r.exitSeen = true
		}
	}
}

// Close closes the reader
func (r *WandbReader) Close() error {
	if r.store != nil {
		return r.store.Close()
	}
	return nil
}
