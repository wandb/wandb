//go:build wireinject

package stream

import (
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
	"github.com/wandb/wandb/core/internal/runhandle"
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
	settings *settings.Settings,
) *Stream {
	wire.Build(streamProviders)
	return &Stream{}
}

var streamProviders = wire.NewSet(
	NewStream,
	wire.Bind(new(api.Peeker), new(*observability.Peeker)),
	wire.Struct(new(observability.Peeker)),
	BaseURLFromSettings,
	CredentialsFromSettings,
	featurechecker.NewServerFeaturesCache,
	filestream.FileStreamProviders,
	filetransfer.NewFileTransferStats,
	flowControlProviders,
	handlerProviders,
	mailbox.New,
	monitor.SystemMonitorProviders,
	NewFileTransferManager,
	NewGraphQLClient,
	observability.NewPrinter,
	provideFileWatcher,
	RecordParserProviders,
	runfiles.UploaderProviders,
	runhandle.New,
	SenderProviders,
	sharedmode.RandomClientID,
	streamLoggerProviders,
	tensorboard.TBHandlerProviders,
	wboperation.NewOperations,
	WriterProviders,
)

func provideFileWatcher(logger *observability.CoreLogger) watcher.Watcher {
	return watcher.New(watcher.Params{Logger: logger})
}
