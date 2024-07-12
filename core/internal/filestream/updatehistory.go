package filestream

import (
	"fmt"
	"time"

	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/pkg/service"
)

// HistoryUpdate contains run metrics from `run.log()`.
type HistoryUpdate struct {
	Record *service.HistoryRecord
}

func (u *HistoryUpdate) Apply(ctx UpdateContext) error {
	rh := runhistory.New()

	for _, item := range u.Record.Item {
		err := rh.SetFromRecord(item)
		if err != nil {
			// TODO: maybe we should shut down filestream if this fails?
			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply history record: %v",
					err,
				))
		}
	}
	line, err := rh.ToExtendedJSON()
	if err != nil {
		return fmt.Errorf(
			"filestream: failed to serialize history: %v", err)
	}

	if len(line) > maxFileLineBytes {
		// We consider this non-blocking. We'll upload a run with some missing
		// data, but it's better than not uploading anything at all, as long
		// as we inform the user.
		ctx.Logger.CaptureWarn(
			"filestream: run history line too long, skipping",
			"len", len(line),
			"max", maxFileLineBytes,
		)
		ctx.Printer.
			AtMostEvery(time.Minute).
			Writef(
				"Skipped uploading run.log() data that exceeded"+
					" size limit (%d > %d).",
				len(line),
				maxFileLineBytes)
	} else {
		ctx.MakeRequest(&FileStreamRequest{
			HistoryLines: []string{string(line)},
		})
	}

	return nil
}
