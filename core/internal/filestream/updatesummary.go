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

func (u *SummaryUpdate) Apply(ctx UpdateContext) error {
	rs := runsummary.New()

	for _, update := range u.Record.Update {
		if err := rs.SetFromRecord(update); err != nil {
			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply summary record: %v",
					err,
				))
		}
	}

	for _, remove := range u.Record.Remove {
		rs.RemoveFromRecord(remove)
	}

	line, err := rs.Serialize()
	if err != nil {
		return fmt.Errorf(
			"filestream: json unmarshal error in SummaryUpdate: %v",
			err,
		)
	}

	if len(line) > maxFileLineBytes {
		// Failing to upload the summary is non-blocking.
		ctx.Logger.CaptureWarn(
			"filestream: run summary line too long, skipping",
			"len", len(line),
			"max", maxFileLineBytes,
		)
		ctx.Printer.
			AtMostEvery(time.Minute).
			Writef(
				"Skipped uploading summary data that exceeded"+
					" size limit (%d > %d).",
				len(line),
				maxFileLineBytes)
	} else {
		ctx.MakeRequest(&FileStreamRequest{
			LatestSummary: string(line),
		})
	}

	return nil
}
