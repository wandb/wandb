package filestream

import (
	"fmt"
	"time"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// StatsUpdate contains system metrics collected at a point in time as the
// legacy StatsRecord, which transaction logs written before the typed record
// still contain.
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
				"filestream",
				fmt.Errorf("filestream: failed to marshal StatsItem: %v", err),
				"key", item.Key,
			)
			continue
		}

		row["system."+item.Key] = val
	}

	return sendEventsRow(ctx, row)
}

// SystemMetricsUpdate contains one typed system metrics sample.
type SystemMetricsUpdate struct {
	StartTime time.Time
	Record    *spb.SystemMetricsRecord
}

func (u *SystemMetricsUpdate) Apply(ctx UpdateContext) error {
	return sendEventsRow(ctx, systemmetrics.LegacyRow(u.Record, u.StartTime))
}

// sendEventsRow appends one line to wandb-events.jsonl.
//
// A row that fails to marshal or exceeds the maximum line length is dropped
// with a logged error; neither blocks the stream.
func sendEventsRow(ctx UpdateContext, row map[string]any) error {
	line, err := simplejsonext.Marshal(row)

	// Override the default max line length if the user has set a custom value.
	maxLineBytes := ctx.Settings.GetFileStreamMaxLineBytes()
	if maxLineBytes == 0 {
		maxLineBytes = defaultMaxFileLineBytes
	}

	switch {
	case err != nil:
		ctx.Logger.CaptureError(
			"filestream",
			fmt.Errorf(
				"filestream: failed to marshal system metrics: %v",
				err,
			),
		)
	case len(line) > int(maxLineBytes):
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
