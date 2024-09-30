package api

import (
	"bufio"
	"bytes"
	"math/rand"
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
) (resp *http.Response, err error) {
	if err := transport.rateLimiter.Wait(req.Context()); err != nil {
		// Errors happen if:
		//   - The request is canceled
		//   - The rate limit exceeds the request deadline
		return nil, err
	}

	transport.rlTracker.TrackRequest()

	// DO NOT MERGE: Slow down all requests and fail some of them.
	time.Sleep(time.Second)
	if rand.Float64() < 0.7 {
		resp, err = transport.delegate.RoundTrip(req)
	} else {
		const response429 = `HTTP/1.1 429 Too Many Requests
Content-Type: text/html
Retry-After: 1

<html>
  <head><title>Too Many Requests</title></head>
  <body>Slow down!!!</body>
</html>
`
		resp, err = http.ReadResponse(
			bufio.NewReader(bytes.NewReader([]byte(response429))),
			req,
		)
	}

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
