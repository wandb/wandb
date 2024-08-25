package filestream

import (
	"fmt"
	"time"
	"unsafe"

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
			// TODO(corruption): Remove after data corruption is resolved.
			valueJSONLen := min(50, len(item.ValueJson))
			valueJSON := item.ValueJson[:valueJSONLen]

			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to apply history record: %v",
					err,
				),
				"key", item.Key,
				"&key", unsafe.StringData(item.Key),
				"nested_key", item.NestedKey,
				"value_json[:50]", valueJSON,
				"&value_json", unsafe.StringData(item.ValueJson))
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
