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

	// An optional responder to use for communicatating back to the user.
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
	if resp != nil && resp.Body != nil && resp.StatusCode >= http.StatusOK {
		// We need to read the response body to send it to the user
		buf, _ := io.ReadAll(resp.Body)
		transport.responder.Write(&service.HttpResponse{
			HttpStatusCode:   int32(resp.StatusCode),
			HttpResponseText: string(buf),
		})
		// Restore the body so it can be read again
		reader := io.NopCloser(bytes.NewReader(buf))
		resp.Body = reader
	}
	return resp, err
}
