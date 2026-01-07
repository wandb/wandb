//go:build wireinject

package runsync

import (
	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/internal/wboperation"
)

func InjectRunSyncerFactory(
	settings *settings.Settings,
	logger *observability.CoreLogger,
) *RunSyncerFactory {
	wire.Build(runSyncerFactoryBindings)
	return &RunSyncerFactory{}
}

var runSyncerFactoryBindings = wire.NewSet(
	wire.Bind(new(api.Peeker), new(*observability.Peeker)),
	wire.Struct(new(observability.Peeker)),
	featurechecker.NewServerFeaturesCache,
	filestream.FileStreamProviders,
	filetransfer.NewFileTransferStats,
	mailbox.New,
	observability.NewPrinter,
	provideFileWatcher,
	runfiles.UploaderProviders,
	runhandle.New,
	runReaderProviders,
	runSyncerProviders,
	sharedmode.RandomClientID,
	stream.BaseURLFromSettings,
	stream.NewBackend,
	stream.NewFileTransferManager,
	stream.NewGraphQLClient,
	stream.RecordParserProviders,
	stream.SenderProviders,
	tensorboard.TBHandlerProviders,
	wboperation.NewOperations,
)

func provideFileWatcher(logger *observability.CoreLogger) watcher.Watcher {
	return watcher.New(watcher.Params{Logger: logger})
}
