package publicapi

import (
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
)

type ApiRequestHandler struct {
	errgroup *errgroup.Group
}

func NewApiRequestHandler() *ApiRequestHandler {
	errgroup := &errgroup.Group{}
	errgroup.SetLimit(10)

	return &ApiRequestHandler{
		errgroup:                  errgroup,
	}
}

func (p *ApiRequestHandler) HandleRequest(
	id string,
	request *spb.ApiRequest,
	respondFn func(response *spb.ServerResponse),
) {
	p.errgroup.Go(func() error {
		return nil
	})
}
