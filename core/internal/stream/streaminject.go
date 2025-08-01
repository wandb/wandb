//go:build wireinject

package stream

import (
	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/randomid"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/watcher"
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
	wire.Bind(new(runwork.ExtraWork), new(runwork.RunWork)),
	wire.Bind(new(api.Peeker), new(*observability.Peeker)),
	wire.Struct(new(observability.Peeker)),
	filetransfer.NewFileTransferStats,
	NewBackend,
	NewFileStream,
	NewFileTransferManager,
	NewGraphQLClient,
	NewRunfilesUploader,
	observability.NewPrinter,
	provideClientID,
	provideFileWatcher,
	provideStreamRunWork,
	streamLoggerProviders,
	wboperation.NewOperations,
)

func provideClientID() ClientID {
	return ClientID(randomid.GenerateUniqueID(32))
}

func provideFileWatcher(logger *observability.CoreLogger) watcher.Watcher {
	return watcher.New(watcher.Params{Logger: logger})
}

func provideStreamRunWork(logger *observability.CoreLogger) runwork.RunWork {
	return runwork.New(BufferSize, logger)
}
