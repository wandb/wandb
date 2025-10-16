package publicapi

import (
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// maxConcurrency is the maximum number of concurrent requests
	// we want to handle at any given time.
	maxConcurrency = 10
)

// APIRequestHandler handles processing API requests
// from the SDK API clients, and returning API responses to those requests.
type APIRequestHandler struct {
	// semaphore is a buffered channel limiting concurrent request handling
	semaphore chan struct{}
}

func NewApiRequestHandler() *APIRequestHandler {
	return &APIRequestHandler{
		semaphore: make(chan struct{}, maxConcurrency),
	}
}

func (p *APIRequestHandler) HandleRequest(
	id string,
	request *spb.ApiRequest,
	respondFn func(response *spb.ServerResponse),
) {
	// block until until we are able to process more requests
	p.semaphore <- struct{}{}
	defer func() { <-p.semaphore }()

	// TODO: Implement request handling logic.
	// For now respond with a place holder response.
	respondFn(&spb.ServerResponse{
		RequestId: id,
	})
}
