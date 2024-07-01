package filestream

import (
	"fmt"

	"github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/pkg/service"
)

// StatsUpdate contains system metrics during the run, e.g. memory usage.
type StatsUpdate struct {
	Record *service.StatsRecord
}

func (u *StatsUpdate) Apply(ctx UpdateContext) error {
	// todo: there is a lot of unnecessary overhead here,
	//  we should prepare all the data in the system monitor
	//  and then send it in one record
	row := make(map[string]interface{})
	row["_wandb"] = true
	timestamp := float64(u.Record.GetTimestamp().Seconds) + float64(u.Record.GetTimestamp().Nanos)/1e9
	row["_timestamp"] = timestamp
	row["_runtime"] = timestamp - ctx.Settings.XStartTime.GetValue()

	for _, item := range u.Record.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			ctx.Logger.CaptureError(
				fmt.Errorf(
					"filestream: failed to marshal StatsItem for key %s: %v",
					item.Key,
					err,
				))
			continue
		}

		row["system."+item.Key] = val
	}

	// marshal the row
	line, err := json.Marshal(row)
	switch {
	case err != nil:
		// This is a non-blocking failure, so we don't return an error.
		ctx.Logger.CaptureError(
			fmt.Errorf(
				"filestream: failed to marshal system metrics: %v",
				err,
			))
	case len(line) > maxFileLineBytes:
		// This is a non-blocking failure as well.
		ctx.Logger.CaptureWarn(
			"filestream: system metrics line too long, skipping",
			"len", len(line),
			"max", maxFileLineBytes,
		)
	default:
		ctx.MakeRequest(&FileStreamRequest{
			EventsLines: []string{string(line)},
		})
	}

	return nil
}
