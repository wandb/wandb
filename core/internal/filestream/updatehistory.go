package filestream

import (
	"context"
	"fmt"
	"time"

	"github.com/wandb/wandb/core/internal/filestreamstats"
	"github.com/wandb/wandb/core/internal/runhistory"
)

// HistoryUpdate contains run metrics from `run.log()`.
type HistoryUpdate struct {
	Row   *runhistory.RunHistory
	Cells int
}

func (u *HistoryUpdate) Apply(ctx UpdateContext) error {
	applyTime := time.Now()

	line, err := u.Row.ToExtendedJSON()
	renderDuration := time.Since(applyTime)
	if err != nil {
		return fmt.Errorf(
			"filestream: failed to serialize history: %v", err)
	}

	ctx.Stats.RecordSegment(
		context.Background(),
		filestreamstats.SegmentUploadRender,
		filestreamstats.StreamHistory,
		renderDuration,
	)

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
			Warnf(
				"Skipped uploading run.log() data that exceeded"+
					" size limit (%d > %d).",
				len(line),
				maxLineBytes,
			)
	} else {
		ctx.MakeRequest(&FileStreamRequest{
			HistoryLines: []string{string(line)},
		})
		ctx.Stats.AddRow(u.Cells)
	}

	return nil
}
