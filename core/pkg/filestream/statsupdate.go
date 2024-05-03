package filestream

import (
	"fmt"

	"github.com/segmentio/encoding/json"
	"github.com/wandb/wandb/core/pkg/service"
)

// StatsUpdate contains system metrics during the run, e.g. memory usage.
type StatsUpdate struct {
	Record *service.StatsRecord
}

func (u *StatsUpdate) Chunk(fs *fileStream) error {
	// todo: there is a lot of unnecessary overhead here,
	//  we should prepare all the data in the system monitor
	//  and then send it in one record
	row := make(map[string]interface{})
	row["_wandb"] = true
	timestamp := float64(u.Record.GetTimestamp().Seconds) + float64(u.Record.GetTimestamp().Nanos)/1e9
	row["_timestamp"] = timestamp
	row["_runtime"] = timestamp - fs.settings.XStartTime.GetValue()

	for _, item := range u.Record.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			e := fmt.Errorf("json unmarshal error: %v, items: %v", err, item)
			errMsg := fmt.Sprintf("sender: sendSystemMetrics: failed to marshal value: %s for key: %s", item.ValueJson, item.Key)
			fs.logger.CaptureError(errMsg, e)
			continue
		}

		row["system."+item.Key] = val
	}

	// marshal the row
	line, err := json.Marshal(row)
	if err != nil {
		// This is a non-blocking failure, so we don't return an error.
		fs.logger.CaptureError("sender: sendSystemMetrics: failed to marshal system metrics", err)
	} else {
		fs.addTransmit(processedChunk{
			fileType: EventsChunk,
			fileLine: string(line),
		})
	}

	return nil
}
