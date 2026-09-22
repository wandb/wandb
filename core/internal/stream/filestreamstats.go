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
// run's upload pipeline. It is owned by the stream, but it is shared by the
// handler, the transaction-log writer, the sender and the filestream.
func streamFileStreamStats(
	logger *observability.CoreLogger,
) *filestreamstats.Stats {
	// The encodings are fixed until the typed history settings exist. Both
	// are read from settings once x_history_value_encoding and
	// x_file_stream_history_encoding land.
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
