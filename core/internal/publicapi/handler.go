package publicapi

import (
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
)

// APIRequestHandler is a handler for processing API requests
// from the SDK API clients.
type APIRequestHandler struct {
	errgroup *errgroup.Group
}

func NewApiRequestHandler() *APIRequestHandler {
	errgroup := &errgroup.Group{}
	errgroup.SetLimit(10)

	return &APIRequestHandler{
		errgroup:                  errgroup,
	}
}

func (p *APIRequestHandler) HandleRequest(
	id string,
	request *spb.ApiRequest,
	respondFn func(response *spb.ServerResponse),
) {
	p.errgroup.Go(func() error {
		// TODO: Implement request handling logic.
		// For now respond with a place holder response.
		respondFn(&spb.ServerResponse{
			RequestId: id,
		})
		return nil
	})
}
