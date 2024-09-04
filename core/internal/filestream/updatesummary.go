package filestream

import (
	"fmt"
	"time"
	"unsafe"

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
			// TODO(corruption): Remove after data corruption is resolved.
			valueJSONLen := min(50, len(update.ValueJson))
			valueJSON := update.ValueJson[:valueJSONLen]

			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply summary record: %v",
					err,
				),
				"key", update.Key,
				"&key", unsafe.StringData(update.Key),
				"nested_key", update.NestedKey,
				"value_json[:50]", valueJSON,
				"&value_json", unsafe.StringData(update.ValueJson))
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
