package filestream

import (
	"fmt"
	"strings"
	"time"

	"github.com/wandb/wandb/core/pkg/service"
)

// rfc3339Micro Modified from time.RFC3339Nano
const rfc3339Micro = "2006-01-02T15:04:05.000000Z07:00"

// LogsUpdate is new lines in a run's console output.
type LogsUpdate struct {
	Record *service.OutputRawRecord
}

func (u *LogsUpdate) Apply(ctx UpdateContext) error {
	// generate compatible timestamp to python iso-format (microseconds without Z)
	t := strings.TrimSuffix(time.Now().UTC().Format(rfc3339Micro), "Z")

	var line string
	switch u.Record.OutputType {
	case service.OutputRawRecord_STDOUT:
		line = fmt.Sprintf("%s %s", t, u.Record.Line)
	case service.OutputRawRecord_STDERR:
		line = fmt.Sprintf("ERROR %s %s", t, u.Record.Line)
	default:
		ctx.Logger.CaptureError(
			fmt.Errorf(
				"filestream: unexpected logs output type %v",
				u.Record.OutputType,
			),
		)

		return nil
	}

	ctx.ModifyRequest(&collectorLogsUpdate{
		line: line,
	})

	return nil
}

type collectorLogsUpdate struct {
	line string
}

func (u *collectorLogsUpdate) Apply(state *CollectorState) {
	state.ConsoleLogLines = append(state.ConsoleLogLines, u.line)
}
