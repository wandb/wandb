package api

import (
	"net/http"
	"time"

	"golang.org/x/time/rate"
)

// A rate-limited HTTP transport for requests to the W&B backend.
//
// Implements [http.RoundTripper] for use as a transport for an HTTP client.
type RateLimitedTransport struct {
	delegate http.RoundTripper

	// Rate limit for all outgoing requests.
	rateLimiter *rate.Limiter

	// Dynamic adjustments to the rate-limit based on server backpressure.
	rlTracker *RateLimitTracker
}

// Rate-limits an HTTP transport for the W&B backend.
func NewRateLimitedTransport(
	delegate http.RoundTripper,
) *RateLimitedTransport {
	return &RateLimitedTransport{
		delegate:    delegate,
		rateLimiter: rate.NewLimiter(maxRequestsPerSecond, maxBurst),
		rlTracker: NewRateLimitTracker(RateLimitTrackerParams{
			MinPerSecond: minRequestsPerSecond,
			MaxPerSecond: maxRequestsPerSecond,

			// TODO: Allow changing these through settings.
			Smoothing:              0.2,
			MinRequestsForEstimate: 5,
		}),
	}
}

func (transport *RateLimitedTransport) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	if err := transport.rateLimiter.Wait(req.Context()); err != nil {
		// Errors happen if:
		//   - The request is canceled
		//   - The rate limit exceeds the request deadline
		return nil, err
	}

	transport.rlTracker.TrackRequest()
	resp, err := transport.delegate.RoundTrip(req)

	if resp != nil {
		transport.processRateLimitHeaders(resp)
	}

	return resp, err
}

func (transport *RateLimitedTransport) processRateLimitHeaders(
	resp *http.Response,
) {
	rateLimit, ok := ParseRateLimitHeaders(resp.Header)
	if !ok {
		return
	}

	transport.rlTracker.UpdateEstimates(time.Now(), rateLimit)
	transport.rateLimiter.SetLimit(rate.Limit(
		transport.rlTracker.TargetRateLimit()))
}
