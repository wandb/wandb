package api

import (
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/time/rate"
)

// RateLimitTransport rate-limits requests to the W&B backend.
//
// Implements [http.RoundTripper] for use as a transport for an HTTP client.
type RateLimitedTransport struct {
	delegate http.RoundTripper
	printer  *observability.Printer

	// rateLimitDomain is a human-readable string that's included in printed
	// messages about rate limits.
	//
	// In W&B there are at least two rate-limit domains: "Filestream" and
	// "GraphQL". This string helps the user know which limit they are
	// hitting.
	rateLimitDomain string

	// rateLimiter is the rate limit for all outgoing requests.
	rateLimiter *rate.Limiter

	// rlTracker makes dynamic adjustments to the rate-limit based on
	// server backpressure.
	rlTracker *RateLimitTracker
}

// Rate-limits an HTTP transport for the W&B backend.
func NewRateLimitedTransport(
	rateLimitDomain string,
	delegate http.RoundTripper,
	printer *observability.Printer,
) *RateLimitedTransport {
	return &RateLimitedTransport{
		delegate:        delegate,
		printer:         printer,
		rateLimiter:     rate.NewLimiter(maxRequestsPerSecond, maxBurst),
		rateLimitDomain: rateLimitDomain,
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
	wait := transport.rateLimiter.Reserve()

	// Should never happen!
	if !wait.OK() {
		return nil, errors.New("api: rate limit seems to be zero")
	}

	if wait.Delay() > 0 {
		transport.printer.
			AtMostEvery(10*time.Second).
			Writef(
				"Rate-limited (%s). Current limit: %.2f requests per second.",
				transport.rateLimitDomain,
				transport.rateLimiter.Limit())

		select {
		case <-time.After(wait.Delay()):
			// Go do the request!
		case <-req.Context().Done():
			return nil, fmt.Errorf(
				"api: while waiting for rate limit: %v",
				req.Context().Err())
		}
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
