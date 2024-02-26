package api

import (
	"net/http"
)

// A rate-limited HTTP transport for requests to the W&B backend.
//
// Implements [http.RoundTripper] for use as a transport for an HTTP client.
type rateLimitedTransport struct {
	backend  *Backend
	delegate http.RoundTripper
}

// Rate-limits an HTTP transport for the W&B backend.
func (backend *Backend) rateLimitedTransport(
	delegate http.RoundTripper,
) *rateLimitedTransport {
	return &rateLimitedTransport{
		backend:  backend,
		delegate: delegate,
	}
}

func (transport *rateLimitedTransport) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	if err := transport.backend.rateLimiter.Wait(req.Context()); err != nil {
		// Errors happen if:
		//   - The request is canceled
		//   - The rate limit exceeds the request deadline
		return nil, err
	}

	return transport.delegate.RoundTrip(req)
}
