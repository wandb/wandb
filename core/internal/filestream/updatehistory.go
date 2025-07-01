package filestream

import (
	"fmt"
	"time"

	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// HistoryUpdate contains run metrics from `run.log()`.
type HistoryUpdate struct {
	Record *spb.HistoryRecord
}

func (u *HistoryUpdate) Apply(ctx UpdateContext) error {
	rh := runhistory.New()

	for _, item := range u.Record.Item {
		err := rh.SetFromRecord(item)
		if err != nil {

			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply history record: %v",
					err,
				),
				"key", item.Key,
				"nested_key", item.NestedKey,
			)
		}
	}
	line, err := rh.ToExtendedJSON()
	if err != nil {
		return fmt.Errorf(
			"filestream: failed to serialize history: %v", err)
	}

	// Override the default max line length if the user has set a custom value.
	maxLineBytes := ctx.Settings.GetFileStreamMaxLineBytes()
	if maxLineBytes == 0 {
		maxLineBytes = defaultMaxFileLineBytes
	}

	if len(line) > int(maxLineBytes) {
		// We consider this non-blocking. We'll upload a run with some missing
		// data, but it's better than not uploading anything at all, as long
		// as we inform the user.
		ctx.Logger.CaptureWarn(
			"filestream: run history line too long, skipping",
			"len", len(line),
			"max", maxLineBytes,
		)
		ctx.Printer.
			AtMostEvery(time.Minute).
			Writef(
				"Skipped uploading run.log() data that exceeded"+
					" size limit (%d > %d).",
				len(line),
				maxLineBytes,
			)
	} else {
		ctx.MakeRequest(&FileStreamRequest{
			HistoryLines: []string{string(line)},
		})
	}

	return nil
}
