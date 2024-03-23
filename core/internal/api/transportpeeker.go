package api

import (
	"net/http"
)

type Peeker interface {
	Peek(*http.Request, *http.Response)
}

// An HTTP transport wrapper that reports HTTP responses back to the client.
type PeekingTransport struct {
	// The underlying transport to use for making requests.
	delegate http.RoundTripper

	// An optional peeker to use for communicatating back to the user.
	peeker Peeker
}

func NewPeekingTransport(
	peeker Peeker,
	delegate http.RoundTripper,
) *PeekingTransport {
	return &PeekingTransport{
		peeker:   peeker,
		delegate: delegate,
	}
}

func (transport *PeekingTransport) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	resp, err := transport.delegate.RoundTrip(req)
	// If there is no peeker, we don't need to do anything
	if transport.peeker != nil {
		transport.peeker.Peek(req, resp)
	}

	return resp, err
}
