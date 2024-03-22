package api

import (
	"bytes"
	"io"
	"net/http"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// A rate-limited HTTP transport for requests to the W&B backend.
// Implements [http.RoundTripper] for use as a transport for an HTTP client.
// With a responder to communicate back to the user about the http responses.
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
	// If there is no responder, we don't need to do anything
	if transport.responder == nil {
		return resp, err
	}
	if resp != nil && resp.StatusCode >= http.StatusOK {
		// we want to read the body and use it to update the response, however
		// we also need to put it back in the response so the calling code
		// can read it
		buf, _ := io.ReadAll(resp.Body)
		reader := io.NopCloser(bytes.NewReader(buf))
		transport.responder.Write(&service.HttpResponse{
			HttpStatusCode:   int32(resp.StatusCode),
			HttpResponseText: string(buf),
		})
		resp.Body = reader
	}
	return resp, err
}
