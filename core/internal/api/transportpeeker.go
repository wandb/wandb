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
type PeekingTransport struct {
	// The underlying transport to use for making requests.
	delegate http.RoundTripper

	// An optional peek to use for communicatating back to the user.
	peek *observability.Printer[*service.HttpResponse]
}

func NewPeekingTransport(
	responder *observability.Printer[*service.HttpResponse],
	delegate http.RoundTripper,
) *PeekingTransport {
	return &PeekingTransport{
		delegate: delegate,
		peek:     responder,
	}
}

func (transport *PeekingTransport) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	resp, err := transport.delegate.RoundTrip(req)
	// If there is no peeker, we don't need to do anything
	if transport.peek == nil {
		return resp, err
	}
	if resp != nil && resp.Body != nil && resp.StatusCode >= http.StatusOK {
		// We need to read the response body to send it to the user
		buf, _ := io.ReadAll(resp.Body)
		transport.peek.Write(&service.HttpResponse{
			HttpStatusCode:   int32(resp.StatusCode),
			HttpResponseText: string(buf),
		})
		// Restore the body so it can be read again
		reader := io.NopCloser(bytes.NewReader(buf))
		resp.Body = reader
	}
	return resp, err
}
