package filestream

import (
	"fmt"
	"slices"

	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/pkg/service"
)

// HistoryUpdate contains run metrics from `run.log()`.
type HistoryUpdate struct {
	Record *service.HistoryRecord
}

func (u *HistoryUpdate) Chunk(fs *fileStream) error {
	items := slices.Clone(u.Record.Item)

	// when logging to the same run with multiple writers, we need to
	// add a client id to the history record
	if fs.clientId != "" {
		items = append(items, &service.HistoryItem{
			Key:       "_client_id",
			ValueJson: fmt.Sprintf(`"%s"`, fs.clientId),
		})
	}

	rh := runhistory.New()
	rh.ApplyChangeRecord(
		items,
		func(err error) {
			// TODO: maybe we should shut down filestream if this fails?
			fs.logger.CaptureError(
				"filestream: failed to apply history record", err)
		},
	)
	line, err := rh.Serialize()
	if err != nil {
		return fmt.Errorf(
			"filestream: failed to serialize history: %v", err)
	}

	fs.addTransmit(&TransmitChunk{
		HistoryLines: []string{string(line)},
	})

	return nil
}
