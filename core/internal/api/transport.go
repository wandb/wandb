package api

import "net/http"

// A rate-limited HTTP transport for requests to the W&B backend.
//
// Implements [http.RoundTripper] for use as a transport for an HTTP client.
type backendTransport struct {
	backend   *Backend
	delegate  http.RoundTripper
	ratelimit rateLimiter
}

// Rate-limits an HTTP transport for the W&B backend.
func (backend *Backend) rateLimitedTransport(
	delegate http.RoundTripper,
) *backendTransport {
	return &backendTransport{
		backend:   backend,
		delegate:  delegate,
		ratelimit: newRateLimiter(backend.logger),
	}
}

func (transport *backendTransport) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	transport.ratelimit.waitIfRateLimited()

	response, err := transport.delegate.RoundTrip(req)

	if response != nil {
		transport.ratelimit.processRateLimitHeaders(response)
	}

	return response, err
}
