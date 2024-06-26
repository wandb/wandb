package filestream

import (
	"fmt"
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/pkg/service"
)

// HistoryUpdate contains run metrics from `run.log()`.
type HistoryUpdate struct {
	Record *service.HistoryRecord
}

func (u *HistoryUpdate) Apply(ctx UpdateContext) error {
	items := slices.Clone(u.Record.Item)

	rh := runhistory.New()
	rh.ApplyChangeRecord(
		items,
		func(err error) {
			// TODO: maybe we should shut down filestream if this fails?
			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply history record: %v",
					err,
				))
		},
	)
	line, err := rh.Serialize()
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
		ctx.Modify(func(buffer *FileStreamRequestBuffer) {
			buffer.HistoryLines = append(buffer.HistoryLines, string(line))
		})
	}

	return nil
}
