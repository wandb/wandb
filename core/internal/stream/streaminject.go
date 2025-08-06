//go:build wireinject

package stream

import (
	"context"
	"log/slog"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// InjectStream returns a new Stream.
func InjectStream(
	commit GitCommitHash,
	gpuResourceManager *monitor.GPUResourceManager,
	debugCorePath DebugCorePath,
	logLevel slog.Level,
	sentry *sentry_ext.Client,
	settings *settings.Settings,
) *Stream {
	wire.Build(streamProviders)
	return &Stream{}
}

var streamProviders = wire.NewSet(
	NewStream,
	wire.Bind(new(runwork.ExtraWork), new(runwork.RunWork)),
	wire.Bind(new(api.Peeker), new(*observability.Peeker)),
	wire.Struct(new(observability.Peeker)),
	featurechecker.NewServerFeaturesCache,
	filestream.FileStreamProviders,
	filetransfer.NewFileTransferStats,
	handlerProviders,
	mailbox.New,
	monitor.SystemMonitorProviders,
	NewBackend,
	NewFileTransferManager,
	NewGraphQLClient,
	NewStreamRun,
	observability.NewPrinter,
	provideFileWatcher,
	provideRunContext,
	provideStreamRunWork,
	RecordParserProviders,
	runfiles.UploaderProviders,
	senderProviders,
	sharedmode.RandomClientID,
	streamLoggerProviders,
	tensorboard.TBHandlerProviders,
	wboperation.NewOperations,
	writerProviders,
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
