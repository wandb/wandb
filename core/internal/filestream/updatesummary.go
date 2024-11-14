package filestream

import (
	"fmt"
	"time"

	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SummaryUpdate contains a run's most recent summary.
type SummaryUpdate struct {
	Record *spb.SummaryRecord
}

func (u *SummaryUpdate) Apply(ctx UpdateContext) error {
	rs := runsummary.New()

	for _, update := range u.Record.Update {
		if err := rs.SetFromRecord(update); err != nil {
			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply summary record: %v",
					err,
				),
				"key", update.Key,
				"nested_key", update.NestedKey,
			)
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

	// Override the default max line length if the user has set a custom value.
	maxLineBytes := ctx.Settings.GetFileStreamMaxLineBytes()
	if maxLineBytes == 0 {
		maxLineBytes = defaultMaxFileLineBytes
	}

	if len(line) > int(maxLineBytes) {
		// Failing to upload the summary is non-blocking.
		ctx.Logger.CaptureWarn(
			"filestream: run summary line too long, skipping",
			"len", len(line),
			"max", maxLineBytes,
		)
		ctx.Printer.
			AtMostEvery(time.Minute).
			Writef(
				"Skipped uploading summary data that exceeded"+
					" size limit (%d > %d).",
				len(line),
				maxLineBytes,
			)
	} else {
		ctx.MakeRequest(&FileStreamRequest{
			LatestSummary: string(line),
		})
	}

	return nil
}
