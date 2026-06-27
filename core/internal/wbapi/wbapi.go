// Package wbapi implements logic for handling "API requests" from clients.
//
// API requests generally query a W&B backend. In practice, these are usually
// GraphQL operations, but some requests can involve more complex combinations
// of GraphQL and other network operations (like file downloads).
package wbapi

import (
	"context"
	"fmt"
	"net/url"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// maxConcurrency is the maximum number of concurrent requests
	// we want to handle at any given time.
	maxConcurrency = 10
)

// WandbAPI processes API requests for a specific account on a W&B deployment.
type WandbAPI struct {
	// semaphore is a buffered channel limiting concurrent request handling
	semaphore chan struct{}

	settings *settings.Settings

	featuresHandler      *FeaturesHandler
	fileStreamHandler    *FileStreamHandler
	fileTransferHandler  *FileTransferHandler
	graphqlHandler       *GraphQLHandler
	runHistoryApiHandler *RunHistoryAPIHandler
}

// New returns a new WandbAPI.
func New(
	s *settings.Settings,
	logger *observability.CoreLogger,
) (*WandbAPI, error) {
	baseURL, err := url.Parse(s.GetBaseURL())
	if err != nil {
		return nil, fmt.Errorf("error parsing base URL: %v", err)
	}

	credentialProvider, err := api.NewCredentialProvider(s, logger.Logger)
	if err != nil {
		return nil, fmt.Errorf("error reading credentials: %v", err)
	}

	graphqlClient := api.NewGQLClient(
		api.WBBaseURL(baseURL),
		"", /*clientID*/
		credentialProvider,
		logger.Logger,
		&observability.Peeker{},
		s,
		s.GetExtraHTTPHeaders(),
	)

	httpClient := retryablehttp.NewClient()
	httpClient.RetryMax = int(s.GetFileTransferMaxRetries())
	httpClient.RetryWaitMin = s.GetFileTransferRetryWaitMin()
	httpClient.RetryWaitMax = s.GetFileTransferRetryWaitMax()
	httpClient.HTTPClient.Timeout = s.GetFileTransferTimeout()
	httpClient.Logger = logger

	fileTransferClient := newFileTransferClient(
		baseURL,
		credentialProvider,
		logger,
		s,
	)
	fileTransferStats := filetransfer.NewFileTransferStats()
	fileTransfers := filetransfer.NewFileTransfers(
		fileTransferClient,
		logger,
		fileTransferStats,
	)
	fileTransferManager := filetransfer.NewFileTransferManager(
		filetransfer.FileTransferManagerOptions{
			Logger:            logger,
			FileTransfers:     fileTransfers,
			FileTransferStats: fileTransferStats,
		},
	)
	featureProvider := featurechecker.New(graphqlClient, logger)

	fileStreamClient := newFileStreamClient(
		baseURL,
		credentialProvider,
		logger,
		s,
	)

	return &WandbAPI{
		semaphore: make(chan struct{}, maxConcurrency),
		settings:  s,

		featuresHandler:      NewFeaturesHandler(featureProvider),
		fileStreamHandler:    NewFileStreamHandler(fileStreamClient, baseURL),
		fileTransferHandler:  NewFileTransferHandler(fileTransferManager),
		graphqlHandler:       NewGraphQLHandler(graphqlClient),
		runHistoryApiHandler: NewRunHistoryAPIHandler(graphqlClient, httpClient),
	}, nil
}

// newFileStreamClient returns a client for posting to the filestream API.
func newFileStreamClient(
	baseURL *url.URL,
	credentialProvider api.CredentialProvider,
	logger *observability.CoreLogger,
	s *settings.Settings,
) api.RetryableClient {
	httpOpts := api.ClientOptions{
		BaseURL:     baseURL,
		RetryPolicy: clients.RetryMostFailures,
		Logger:      logger.Logger,

		RetryMax:        filestream.DefaultRetryMax,
		RetryWaitMin:    filestream.DefaultRetryWaitMin,
		RetryWaitMax:    filestream.DefaultRetryWaitMax,
		NonRetryTimeout: filestream.DefaultNonRetryTimeout,

		Proxy: clients.ProxyFn(
			s.GetHTTPProxy(),
			s.GetHTTPSProxy(),
		),

		InsecureDisableSSL: s.IsInsecureDisableSSL(),
		ExtraHeaders:       s.GetExtraHTTPHeaders(),
		CredentialProvider: credentialProvider,
	}

	if retryMax := s.GetFileStreamMaxRetries(); retryMax > 0 {
		httpOpts.RetryMax = int(retryMax)
	}
	if retryWaitMin := s.GetFileStreamRetryWaitMin(); retryWaitMin > 0 {
		httpOpts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := s.GetFileStreamRetryWaitMax(); retryWaitMax > 0 {
		httpOpts.RetryWaitMax = retryWaitMax
	}
	if timeout := s.GetFileStreamTimeout(); timeout > 0 {
		httpOpts.NonRetryTimeout = timeout
	}

	return api.NewClient(httpOpts)
}

func newFileTransferClient(
	baseURL *url.URL,
	credentialProvider api.CredentialProvider,
	logger *observability.CoreLogger,
	s *settings.Settings,
) api.RetryableClient {
	httpOpts := api.ClientOptions{
		BaseURL:     baseURL,
		RetryPolicy: filetransfer.FileTransferRetryPolicy,
		Logger:      logger.Logger,

		RetryMax:        filetransfer.DefaultRetryMax,
		RetryWaitMin:    filetransfer.DefaultRetryWaitMin,
		RetryWaitMax:    filetransfer.DefaultRetryWaitMax,
		NonRetryTimeout: filetransfer.DefaultNonRetryTimeout,

		Proxy: clients.ProxyFn(
			s.GetHTTPProxy(),
			s.GetHTTPSProxy(),
		),

		InsecureDisableSSL: s.IsInsecureDisableSSL(),
		ExtraHeaders:       s.GetExtraHTTPHeaders(),
		CredentialProvider: credentialProvider,
	}

	if retryMax := s.GetFileTransferMaxRetries(); retryMax > 0 {
		httpOpts.RetryMax = int(retryMax)
	}
	if retryWaitMin := s.GetFileTransferRetryWaitMin(); retryWaitMin > 0 {
		httpOpts.RetryWaitMin = retryWaitMin
	}
	if retryWaitMax := s.GetFileTransferRetryWaitMax(); retryWaitMax > 0 {
		httpOpts.RetryWaitMax = retryWaitMax
	}
	if timeout := s.GetFileTransferTimeout(); timeout > 0 {
		httpOpts.NonRetryTimeout = timeout
	}

	return api.NewClient(httpOpts)
}

// HandleRequest handles an API request and returns an API response,
// or nil if not response is needed.
//
// HandleRequest blocks until the request is processed.
func (p *WandbAPI) HandleRequest(
	ctx context.Context,
	id string,
	request *spb.ApiRequest,
) *spb.ApiResponse {
	if err := ctx.Err(); err != nil {
		return apiErrorResponse(err.Error(), 0)
	}

	// Block until we are able to process more requests, unless the client is
	// tearing down and the request context is cancelled first.
	select {
	case p.semaphore <- struct{}{}:
	case <-ctx.Done():
		return apiErrorResponse(ctx.Err().Error(), 0)
	}
	defer func() { <-p.semaphore }()

	switch req := request.Request.(type) {
	case *spb.ApiRequest_FeaturesRequest:
		return p.featuresHandler.HandleRequest(ctx, req.FeaturesRequest)
	case *spb.ApiRequest_DownloadFileRequest:
		return p.fileTransferHandler.HandleDownloadFile(ctx, req.DownloadFileRequest)
	case *spb.ApiRequest_UploadFileRequest:
		return p.fileTransferHandler.HandleUploadFile(ctx, req.UploadFileRequest)
	case *spb.ApiRequest_MarkRunFilesUploadedRequest:
		return p.fileStreamHandler.HandleMarkRunFilesUploaded(ctx, req.MarkRunFilesUploadedRequest)
	case *spb.ApiRequest_GraphqlRequest:
		return p.graphqlHandler.HandleRequest(ctx, req.GraphqlRequest)
	case *spb.ApiRequest_ReadRunHistoryRequest:
		return p.runHistoryApiHandler.HandleRequest(ctx, req.ReadRunHistoryRequest)
	}

	return nil
}
