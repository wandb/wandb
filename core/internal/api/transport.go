package api

import (
	"net/http"

	"golang.org/x/time/rate"
)

const (
	maxRequestsPerSecond = 100
	maxBurst             = 20
)

// A rate-limited HTTP transport for requests to the W&B backend.
//
// Implements [http.RoundTripper] for use as a transport for an HTTP client.
type rateLimitedTransport struct {
	backend   *Backend
	delegate  http.RoundTripper
	ratelimit *rate.Limiter
}

// Rate-limits an HTTP transport for the W&B backend.
func (backend *Backend) rateLimitedTransport(
	delegate http.RoundTripper,
) *rateLimitedTransport {
	return &rateLimitedTransport{
		backend:   backend,
		delegate:  delegate,
		ratelimit: rate.NewLimiter(maxRequestsPerSecond, maxBurst),
	}
}

func (transport *rateLimitedTransport) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	if err := transport.ratelimit.Wait(req.Context()); err != nil {
		// Errors happen if:
		//   - The request is canceled
		//   - The rate limit exceeds the request deadline
		return nil, err
	}

	return transport.delegate.RoundTrip(req)
}
