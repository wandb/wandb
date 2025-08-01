//go:build wireinject

package stream

import (
	"context"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/tensorboard"
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
		"Commit",
		"GPUResourceManager",
		"Settings",
		"Sentry",
		"LogLevel",
	),
	wire.Bind(new(runwork.ExtraWork), new(runwork.RunWork)),
	wire.Bind(new(api.Peeker), new(*observability.Peeker)),
	wire.Struct(new(observability.Peeker)),
	wire.Struct(new(RecordParser), "*"),
	featurechecker.NewServerFeaturesCache,
	filetransfer.NewFileTransferStats,
	handlerProviders,
	mailbox.New,
	monitor.SystemMonitorProviders,
	NewBackend,
	NewFileStream,
	NewFileTransferManager,
	NewGraphQLClient,
	NewRunfilesUploader,
	NewStreamRun,
	observability.NewPrinter,
	provideFileWatcher,
	provideRunContext,
	provideStreamRunWork,
	senderProviders,
	sharedmode.RandomClientID,
	streamLoggerProviders,
	tensorboard.TBHandlerProviders,
	wboperation.NewOperations,
)

func provideFileWatcher(logger *observability.CoreLogger) watcher.Watcher {
	return watcher.New(watcher.Params{Logger: logger})
}

func provideRunContext(extraWork runwork.ExtraWork) context.Context {
	return extraWork.BeforeEndCtx()
}

func provideStreamRunWork(logger *observability.CoreLogger) runwork.RunWork {
	return runwork.New(BufferSize, logger)
}
