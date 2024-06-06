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

	opts := api.ClientOptions{
		RetryMax:        filestream.DefaultRetryMax,
		RetryWaitMin:    filestream.DefaultRetryWaitMin,
		RetryWaitMax:    filestream.DefaultRetryWaitMax,
		NonRetryTimeout: filestream.DefaultNonRetryTimeout,
		ExtraHeaders:    fileStreamHeaders,
		NetworkPeeker:   peeker,
	}
	if retryMax := settings.Proto.GetXFileStreamRetryMax(); retryMax != nil {
		opts.RetryMax = int(retryMax.GetValue())
	}
	if retryWaitMin := settings.Proto.GetXFileStreamRetryWaitMinSeconds(); retryWaitMin != nil {
		opts.RetryWaitMin = clients.SecondsToDuration(retryWaitMin.GetValue())
	}
	if retryWaitMax := settings.Proto.GetXFileStreamRetryWaitMaxSeconds(); retryWaitMax != nil {
		opts.RetryWaitMax = clients.SecondsToDuration(retryWaitMax.GetValue())
	}
	if timeout := settings.Proto.GetXFileStreamTimeoutSeconds(); timeout != nil {
		opts.NonRetryTimeout = clients.SecondsToDuration(timeout.GetValue())
	}

	fileStreamRetryClient := backend.NewClient(opts)

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
