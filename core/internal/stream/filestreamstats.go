package stream

import (
	"errors"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/filestreamstats"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
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
	settings2 *settings.Settings,
) *filestreamstats.Stats {
	valueEncoding, err := valueEncoding(settings2)
	if err != nil {
		logger.CaptureError("stream", err)
	}
	stats, err := filestreamstats.New(
		logger.TelemetryRecorder,
		valueEncoding,
		filestreamstats.WireEncodingJSONL,
	)
	if err != nil {
		logger.CaptureError("stream", err)
	}
	return stats
}

func valueEncoding(settings2 *settings.Settings) (string, error) {
	jsonEnabled := settings2.IsHistoryValueEncodingJSON()
	typedEnabled := settings2.IsHistoryValueEncodingTyped()
	switch {
	case jsonEnabled && typedEnabled:
		return filestreamstats.ValueEncodingJSONTyped, nil
	case jsonEnabled:
		return filestreamstats.ValueEncodingJSON, nil
	case typedEnabled:
		return filestreamstats.ValueEncodingTyped, nil
	default:
		return "", errors.New("no history value encoding enabled")
	}
}
