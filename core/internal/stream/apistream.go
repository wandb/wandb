package stream

import (
	"log/slog"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type APIStreamParams struct {
	Settings   *settings.Settings
	Sentry     *sentry_ext.Client
	LoggerPath string
	LogLevel   slog.Level
}

type APIStream struct {

	// logger writes debug logs for the run.
	logger *observability.CoreLogger

	// wg is the WaitGroup for the stream
	wg sync.WaitGroup

	// settings is the settings for the stream
	settings *settings.Settings

	// sender is the sender for the stream
	sender *APISender

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry_ext.Client

	// ID is a unique ID for the stream
	ID string
}

type APISender struct {
	// featureProvider checks server capabilities.
	featureProvider *featurechecker.ServerFeaturesCache

	// graphqlClient is used for GraphQL operations to the W&B backend.
	graphqlClient graphql.Client

	// fileTransferManager is the file uploader/downloader
	fileTransferManager filetransfer.FileTransferManager
}

func NewAPIStream(params APIStreamParams) *APIStream {
	loggerFile := streamLoggerFile(params.Settings)
	logger := streamLogger(
		loggerFile,
		params.Settings,
		params.Sentry,
		params.LogLevel,
	)

	return &APIStream{
		logger:       logger,
		sentryClient: params.Sentry,
		settings:     params.Settings,
		dispatcher:   NewDispatcher(logger),
	}
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *APIStream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// UpdateSettings updates the stream's settings with the given settings.
func (s *APIStream) UpdateSettings(newSettings *settings.Settings) {
	s.settings = newSettings
}

// GetSettings returns the stream's settings.
func (s *APIStream) GetSettings() *settings.Settings {
	return s.settings
}

func (s *APIStream) HandleRecord(record *spb.Record) {}

func (s *APIStream) Close() {}

func (s *APIStream) FinishAndClose(exitCode int32) {}
