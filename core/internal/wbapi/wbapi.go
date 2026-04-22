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
	"github.com/wandb/wandb/core/internal/featurechecker"
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

	featureProvider := featurechecker.New(graphqlClient, logger)

	return &WandbAPI{
		semaphore: make(chan struct{}, maxConcurrency),
		settings:  s,

		featuresHandler:      NewFeaturesHandler(featureProvider),
		runHistoryApiHandler: NewRunHistoryAPIHandler(graphqlClient, httpClient),
	}, nil
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
	// block until until we are able to process more requests
	p.semaphore <- struct{}{}
	defer func() { <-p.semaphore }()

	switch req := request.Request.(type) {
	case *spb.ApiRequest_FeaturesRequest:
		return p.featuresHandler.HandleRequest(ctx, req.FeaturesRequest)
	case *spb.ApiRequest_ReadRunHistoryRequest:
		// TODO: Propagate ctx here.
		return p.runHistoryApiHandler.HandleRequest(req.ReadRunHistoryRequest)
	}

	return nil
}
