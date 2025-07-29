//go:build wireinject

package stream

import (
	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// InjectStream returns a new Stream.
func InjectStream(params StreamParams) *Stream {
	wire.Build(streamProviders)
	return &Stream{}
}

var streamProviders = wire.NewSet(
	NewStream,
	wire.FieldsOf(
		new(StreamParams),
		"Settings",
		"Sentry",
		"LogLevel",
	),
	provideStreamRunWork,
	streamLoggerProviders,
	wboperation.NewOperations,
)

func provideStreamRunWork(logger *observability.CoreLogger) runwork.RunWork {
	return runwork.New(BufferSize, logger)
}
