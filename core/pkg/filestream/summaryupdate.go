package filestream

import (
	"fmt"
	"time"

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

	if len(line) > maxFileLineBytes {
		// Failing to upload the summary is non-blocking.
		fs.logger.CaptureWarn(
			"filestream: run summary line too long, skipping",
			"len", len(line),
			"max", maxFileLineBytes,
		)
		fs.printer.
			AtMostEvery(time.Minute).
			Write("Skipped uploading summary data that exceeded size limit.")
	} else {
		fs.addTransmit(&TransmitChunk{
			LatestSummary: string(line),
		})
	}

	return nil
}
