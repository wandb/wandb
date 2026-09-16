package filestream

import (
	"fmt"
	"time"

	"github.com/wandb/wandb/core/internal/runhistory"
)

// HistoryUpdate contains run metrics from `run.log()`.
type HistoryUpdate struct {
	Row *runhistory.RunHistory
}

func (u *HistoryUpdate) Apply(ctx UpdateContext) error {
	cells := u.Row.NumMetrics()
	renderStart := time.Now()
	line, err := u.Row.ToExtendedJSON()
	renderTime := time.Since(renderStart)
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
			Warnf(
				"Skipped uploading run.log() data that exceeded"+
					" size limit (%d > %d).",
				len(line),
				maxLineBytes,
			)
		ctx.EncodeStats.AddSkippedOversizeRow()
	} else {
		ctx.EncodeStats.AddHistoryRow(cells, len(line), renderTime)
		ctx.MakeRequest(&FileStreamRequest{
			HistoryLines: []string{string(line)},
		})
	}

	return nil
}
