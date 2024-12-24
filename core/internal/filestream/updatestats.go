package filestream

import (
	"fmt"
	"time"

	"github.com/wandb/simplejsonext"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// StatsUpdate contains system metrics collected at a point in time.
type StatsUpdate struct {
	StartTime time.Time
	Record    *spb.StatsRecord
}

func (u *StatsUpdate) Apply(ctx UpdateContext) error {
	row := make(map[string]interface{})

	row["_wandb"] = true
	timestamp := u.Record.GetTimestamp()

	row["_timestamp"] = float64(timestamp.Seconds) + float64(timestamp.Nanos)/1e9
	row["_runtime"] = timestamp.AsTime().Sub(u.StartTime).Seconds()

	for _, item := range u.Record.Item {
		val, err := simplejsonext.UnmarshalString(item.ValueJson)
		if err != nil {
			ctx.Logger.CaptureError(
				fmt.Errorf("filestream: failed to marshal StatsItem: %v", err),
				"key", item.Key,
			)
			continue
		}

		row["system."+item.Key] = val
	}

	line, err := simplejsonext.Marshal(row)

	// Override the default max line length if the user has set a custom value.
	maxLineBytes := ctx.Settings.GetFileStreamMaxLineBytes()
	if maxLineBytes == 0 {
		maxLineBytes = defaultMaxFileLineBytes
	}

	switch {
	case err != nil:
		// This is a non-blocking failure, so we don't return an error.
		ctx.Logger.CaptureError(
			fmt.Errorf(
				"filestream: failed to marshal system metrics: %v",
				err,
			))
	case len(line) > int(maxLineBytes):
		// This is a non-blocking failure as well.
		ctx.Logger.CaptureWarn(
			"filestream: system metrics line too long, skipping",
			"len", len(line),
			"max", maxLineBytes,
		)
	default:
		ctx.MakeRequest(&FileStreamRequest{
			EventsLines: []string{string(line)},
		})
	}

	return nil
}
