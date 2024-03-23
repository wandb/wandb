package server

// This file contains functions to construct the objects used by a Stream.

import (
	"net/url"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/shared"
	"github.com/wandb/wandb/core/pkg/filestream"
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

func NewFileStream(
	backend *api.Backend,
	logger *observability.CoreLogger,
	settings *settings.Settings,
) *filestream.FileStream {
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
	})

	return filestream.NewFileStream(
		filestream.WithSettings(settings.Proto),
		filestream.WithLogger(logger),
		filestream.WithAPIClient(fileStreamRetryClient),
		filestream.WithClientId(shared.ShortID(32)),
	)
}

func NewFileTransferManager(
	fileStream *filestream.FileStream,
	logger *observability.CoreLogger,
	settings *settings.Settings,
) filetransfer.FileTransferManager {
	fileTransferRetryClient := retryablehttp.NewClient()
	fileTransferRetryClient.Logger = logger
	fileTransferRetryClient.CheckRetry = clients.CheckRetry
	fileTransferRetryClient.RetryMax = int(settings.Proto.GetXFileTransferRetryMax().GetValue())
	fileTransferRetryClient.RetryWaitMin = clients.SecondsToDuration(settings.Proto.GetXFileTransferRetryWaitMinSeconds().GetValue())
	fileTransferRetryClient.RetryWaitMax = clients.SecondsToDuration(settings.Proto.GetXFileTransferRetryWaitMaxSeconds().GetValue())
	fileTransferRetryClient.HTTPClient.Timeout = clients.SecondsToDuration(settings.Proto.GetXFileTransferTimeoutSeconds().GetValue())
	fileTransferRetryClient.Backoff = clients.ExponentialBackoffWithJitter

	defaultFileTransfer := filetransfer.NewDefaultFileTransfer(
		logger,
		fileTransferRetryClient,
	)
	return filetransfer.NewFileTransferManager(
		filetransfer.WithLogger(logger),
		filetransfer.WithSettings(settings.Proto),
		filetransfer.WithFileTransfer(defaultFileTransfer),
		filetransfer.WithFSCChan(fileStream.GetInputChan()),
	)
}
