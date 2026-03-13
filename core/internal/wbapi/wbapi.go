// Package wbapi implements logic for handling "API requests" from clients.
//
// API requests generally query a W&B backend. In practice, these are usually
// GraphQL operations, but some requests can involve more complex combinations
// of GraphQL and other network operations (like file downloads).
package wbapi

import (
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

	runHistoryApiHandler *RunHistoryAPIHandler
}

// New returns a new WandbAPI.
func New(s *settings.Settings) *WandbAPI {
	return &WandbAPI{
		semaphore:            make(chan struct{}, maxConcurrency),
		settings:             s,
		runHistoryApiHandler: NewRunHistoryAPIHandler(s),
	}
}

// HandleRequest handles an API request and returns an API response,
// or nil if not response is needed.
//
// HandleRequest Blocks until the request is processed.
func (p *WandbAPI) HandleRequest(
	id string,
	request *spb.ApiRequest,
) *spb.ApiResponse {
	// block until until we are able to process more requests
	p.semaphore <- struct{}{}
	defer func() { <-p.semaphore }()

	if _, ok := request.Request.(*spb.ApiRequest_ReadRunHistoryRequest); ok {
		return p.runHistoryApiHandler.HandleRequest(
			request.GetReadRunHistoryRequest(),
		)
	}

	return nil
}
