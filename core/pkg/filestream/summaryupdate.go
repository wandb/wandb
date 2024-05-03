package filestream

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/pkg/service"
)

// SummaryUpdate contains a run's most recent summary.
type SummaryUpdate struct {
	Record *service.SummaryRecord
}

func (u *SummaryUpdate) Chunk(fs *fileStream) error {
	rs := runsummary.New()
	rs.ApplyChangeRecord(
		u.Record,
		func(err error) {
			// TODO: maybe we should shut down filestream if this fails?
			fs.logger.CaptureError(
				"filestream: failed to apply summary record", err)
		},
	)

	line, err := rs.Serialize()
	if err != nil {
		return fmt.Errorf(
			"filestream: json unmarshal error in SummaryUpdate: %v",
			err,
		)
	}

	fs.addTransmit(&TransmitChunk{
		LatestSummary: string(line),
	})

	return nil
}
