package filestream

import "time"

// SummaryUpdate contains a run's most recent summary.
type SummaryUpdate struct {
	SummaryJSON string
}

func (u *SummaryUpdate) Apply(ctx UpdateContext) error {
	// Override the default max line length if the user has set a custom value.
	maxLineBytes := ctx.Settings.GetFileStreamMaxLineBytes()
	if maxLineBytes == 0 {
		maxLineBytes = defaultMaxFileLineBytes
	}

	if len(u.SummaryJSON) > int(maxLineBytes) {
		// Failing to upload the summary is non-blocking.
		ctx.Logger.CaptureWarn(
			"filestream: run summary line too long, skipping",
			"len", len(u.SummaryJSON),
			"max", maxLineBytes,
		)
		ctx.Printer.
			AtMostEvery(time.Minute).
			Writef(
				"Skipped uploading summary data that exceeded"+
					" size limit (%d > %d).",
				len(u.SummaryJSON),
				maxLineBytes,
			)
	} else {
		ctx.MakeRequest(&FileStreamRequest{
			LatestSummary: u.SummaryJSON,
		})
	}

	return nil
}
