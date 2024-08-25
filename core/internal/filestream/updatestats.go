package filestream

import (
	"fmt"
	"time"
	"unsafe"

	"github.com/wandb/simplejsonext"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// StatsUpdate contains system metrics during the run, e.g. memory usage.
type StatsUpdate struct {
	StartTime time.Time
	Record    *spb.StatsRecord
}

func (u *StatsUpdate) Apply(ctx UpdateContext) error {
	// todo: there is a lot of unnecessary overhead here,
	//  we should prepare all the data in the system monitor
	//  and then send it in one record
	row := make(map[string]interface{})
	row["_wandb"] = true
	timestamp := float64(u.Record.GetTimestamp().Seconds) + float64(u.Record.GetTimestamp().Nanos)/1e9
	row["_timestamp"] = timestamp
	row["_runtime"] = u.Record.Timestamp.AsTime().Sub(u.StartTime).Seconds()

	for _, item := range u.Record.Item {
		val, err := simplejsonext.UnmarshalString(item.ValueJson)
		if err != nil {
			// TODO(corruption): Remove after data corruption is resolved.
			valueJSONLen := min(50, len(item.ValueJson))
			valueJSON := item.ValueJson[:valueJSONLen]

			ctx.Logger.CaptureError(
				fmt.Errorf("filestream: failed to marshal StatsItem: %v", err),
				"key", item.Key,
				"&key", unsafe.StringData(item.Key),
				"value_json[:50]", valueJSON,
				"&value_json", unsafe.StringData(item.ValueJson))
			continue
		}

		row["system."+item.Key] = val
	}

	line, err := simplejsonext.Marshal(row)
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
