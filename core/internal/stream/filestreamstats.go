package stream

import (
	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/filestreamstats"
	"github.com/wandb/wandb/core/internal/observability"
)

// fileStreamStatsProviders provides the run's upload-cost accumulator.
var fileStreamStatsProviders = wire.NewSet(
	streamFileStreamStats,
)

// streamFileStreamStats returns the stats object that measures the cost of the
// run's upload pipeline. It is owned by the stream, but the same instance is
// shared by the handler, the transaction-log writer, the sender and the
// filestream.
func streamFileStreamStats(
	logger *observability.CoreLogger,
) *filestreamstats.Stats {
	// Only the legacy JSON/JSONL encodings are available until
	// the typed history formats are enabled.
	stats, err := filestreamstats.New(
		logger.TelemetryRecorder,
		filestreamstats.ValueEncodingJSON,
		filestreamstats.WireEncodingJSONL,
	)
	if err != nil {
		logger.CaptureError("stream", err)
	}
	return stats
}
