package api

import (
	"net/http"
	"strconv"
	"time"

	"golang.org/x/time/rate"
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

	transport.backend.rlTracker.TrackRequest()
	resp, err := transport.delegate.RoundTrip(req)

	if resp != nil {
		transport.processRateLimitHeaders(resp)
	}

	return resp, err
}

func (transport *rateLimitedTransport) processRateLimitHeaders(
	resp *http.Response,
) {
	rlRemaining, err :=
		strconv.ParseFloat(resp.Header.Get("RateLimit-Remaining"), 64)
	if err != nil {
		return
	}

	rlReset, err :=
		strconv.ParseFloat(resp.Header.Get("RateLimit-Reset"), 64)
	if err != nil {
		return
	}

	transport.backend.rlTracker.UpdateEstimates(
		time.Now(),
		rlRemaining,
		rlReset,
	)

	transport.backend.rateLimiter.SetLimit(rate.Limit(
		transport.backend.rlTracker.TargetRateLimit()))
}
