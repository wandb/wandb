package api

import (
	"net/http"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type RateLimitedTransportWithResponder struct {
	// The underlying rate-limited transport.
	delegate *RateLimitedTransport

	// The responder to use for communicatating back to the user.
	responder *observability.Printer[*service.HttpResponse]
}

func NewRateLimitedTransportWithResponder(
	delegate http.RoundTripper,
	responder *observability.Printer[*service.HttpResponse],
) *RateLimitedTransportWithResponder {
	return &RateLimitedTransportWithResponder{
		delegate:  NewRateLimitedTransport(delegate),
		responder: responder,
	}
}

func (transport *RateLimitedTransportWithResponder) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	resp, err := transport.delegate.RoundTrip(req)
	if resp != nil && resp.StatusCode >= http.StatusOK {
		transport.responder.Write(&service.HttpResponse{
			HttpStatusCode:   int32(resp.StatusCode),
			HttpResponseText: resp.Status,
		})
	}
	return resp, err
}
