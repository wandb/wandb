package server

// This file contains functions to construct the objects used by a Stream.

import (
	"context"
	"fmt"
	"maps"
	"net/url"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
)

// NewBackend returns a Backend or nil if we're offline.
func NewBackend(
	logger *observability.CoreLogger,
	settings *settings.Settings,
) *api.Backend {
	if settings.IsOffline() {
		return nil
	}

	baseURL, err := url.Parse(settings.Proto.GetBaseUrl().GetValue())
	if err != nil {
		logger.CaptureFatalAndPanic("sender: failed to parse base URL", err)
	}
	return api.New(api.BackendOptions{
		BaseURL: baseURL,
		Logger:  logger.Logger,
		APIKey:  settings.GetAPIKey(),
	})
}

func NewGraphQLClient(
	backend *api.Backend,
	settings *settings.Settings,
	peeker *observability.Peeker,
) graphql.Client {
	graphqlHeaders := map[string]string{
		"X-WANDB-USERNAME":   settings.Proto.GetUsername().GetValue(),
		"X-WANDB-USER-EMAIL": settings.Proto.GetEmail().GetValue(),
	}
	maps.Copy(graphqlHeaders, settings.Proto.GetXExtraHttpHeaders().GetValue())

	httpClient := backend.NewClient(api.ClientOptions{
		RetryPolicy:     clients.CheckRetry,
		RetryMax:        int(settings.Proto.GetXGraphqlRetryMax().GetValue()),
		RetryWaitMin:    clients.SecondsToDuration(settings.Proto.GetXGraphqlRetryWaitMinSeconds().GetValue()),
		RetryWaitMax:    clients.SecondsToDuration(settings.Proto.GetXGraphqlRetryWaitMaxSeconds().GetValue()),
		NonRetryTimeout: clients.SecondsToDuration(settings.Proto.GetXGraphqlTimeoutSeconds().GetValue()),
		ExtraHeaders:    graphqlHeaders,
		NetworkPeeker:   peeker,
	})
	endpoint := fmt.Sprintf("%s/graphql", settings.Proto.GetBaseUrl().GetValue())

	return graphql.NewClient(endpoint, httpClient)
}

func NewFileStream(
	backend *api.Backend,
	logger *observability.CoreLogger,
	printer *observability.Printer,
	settings *settings.Settings,
	peeker api.Peeker,
) filestream.FileStream {
	fileStreamHeaders := map[string]string{}
	if settings.Proto.GetXShared().GetValue() {
		fileStreamHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
	}

	fileStreamRetryClient := backend.NewClient(api.ClientOptions{
		RetryMax:        int(settings.Proto.GetXFileStreamRetryMax().GetValue()),
		RetryWaitMin:    clients.SecondsToDuration(settings.Proto.GetXFileStreamRetryWaitMinSeconds().GetValue()),
		RetryWaitMax:    clients.SecondsToDuration(settings.Proto.GetXFileStreamRetryWaitMaxSeconds().GetValue()),
		NonRetryTimeout: clients.SecondsToDuration(settings.Proto.GetXFileStreamTimeoutSeconds().GetValue()),
		ExtraHeaders:    fileStreamHeaders,
		NetworkPeeker:   peeker,
	})

	params := filestream.FileStreamParams{
		Settings:  settings.Proto,
		Logger:    logger,
		Printer:   printer,
		ApiClient: fileStreamRetryClient,
	}

	return filestream.NewFileStream(params)
}

func NewFileTransferManager(
	fileTransferStats filetransfer.FileTransferStats,
	logger *observability.CoreLogger,
	settings *settings.Settings,
) filetransfer.FileTransferManager {
	fileTransferRetryClient := retryablehttp.NewClient()
	fileTransferRetryClient.Logger = logger
	fileTransferRetryClient.CheckRetry = filetransfer.FileTransferRetryPolicy
	fileTransferRetryClient.RetryMax = int(settings.Proto.GetXFileTransferRetryMax().GetValue())
	fileTransferRetryClient.RetryWaitMin = clients.SecondsToDuration(settings.Proto.GetXFileTransferRetryWaitMinSeconds().GetValue())
	fileTransferRetryClient.RetryWaitMax = clients.SecondsToDuration(settings.Proto.GetXFileTransferRetryWaitMaxSeconds().GetValue())
	fileTransferRetryClient.HTTPClient.Timeout = clients.SecondsToDuration(settings.Proto.GetXFileTransferTimeoutSeconds().GetValue())
	fileTransferRetryClient.Backoff = clients.ExponentialBackoffWithJitter
	fileTransfers := filetransfer.NewFileTransfers(
		fileTransferRetryClient,
		logger,
		fileTransferStats,
	)
	return filetransfer.NewFileTransferManager(
		filetransfer.WithLogger(logger),
		filetransfer.WithSettings(settings.Proto),
		filetransfer.WithFileTransfers(fileTransfers),
		filetransfer.WithFileTransferStats(fileTransferStats),
	)
}

func NewRunfilesUploader(
	ctx context.Context,
	logger *observability.CoreLogger,
	settings *settings.Settings,
	fileStream filestream.FileStream,
	fileTransfer filetransfer.FileTransferManager,
	fileWatcher watcher.Watcher,
	graphQL graphql.Client,
) runfiles.Uploader {
	return runfiles.NewUploader(runfiles.UploaderParams{
		Ctx:          ctx,
		Logger:       logger,
		Settings:     settings,
		FileStream:   fileStream,
		FileTransfer: fileTransfer,
		GraphQL:      graphQL,
		FileWatcher:  fileWatcher,
		BatchDelay:   waiting.NewDelay(50 * time.Millisecond),
	})
}
