package publicapi

import (
	"github.com/wandb/wandb/core/internal/publicapi/work"
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
		errgroup: errgroup,
	}
}

func (p *ApiRequestHandler) HandleRequest(
	id string,
	request *spb.ApiRequest,
	respondFn func(response *spb.ServerResponse),
) {
	p.errgroup.Go(func() error {
		work := p.parseApiRequest(request)
		if work == nil {
			return nil
		}

		apiResponse := work.Process()
		respondFn(&spb.ServerResponse{
			RequestId: id,
			ServerResponseType: &spb.ServerResponse_ApiResponse{
				ApiResponse: apiResponse,
			},
		})
		return nil
	})
}

// parseApiRequest parses an API request and returns the appropriate work item,
// in order to process the request.
func (p *ApiRequestHandler) parseApiRequest(
	request *spb.ApiRequest,
) work.ApiWork {
	return &work.NoopWork{}
}
