package api

import (
	"net/http"
	"time"

	"github.com/wandb/wandb/core/internal/httplayers"
	"golang.org/x/time/rate"
)

// rateLimitWrapper adds dynamic rate limiting to an HTTP request.
type rateLimitWrapper struct {
	// rateLimiter is the dynamic rate limit for outgoing requests.
	rateLimiter *rate.Limiter

	// rlTracker optimizes the rate limit based on response headers.
	rlTracker *RateLimitTracker
}

// ResponseBasedRateLimiter rate limits outgoing requests based on RateLimit
// headers in responses.
func ResponseBasedRateLimiter() httplayers.HTTPWrapper {
	return rateLimitWrapper{
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

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (transport rateLimitWrapper) WrapHTTP(
	send httplayers.HTTPDoFunc,
) httplayers.HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		if err := transport.rateLimiter.Wait(req.Context()); err != nil {
			// Errors happen if:
			//   - The request is canceled
			//   - The rate limit exceeds the request deadline
			return nil, httplayers.URLError(req, err)
		}

		transport.rlTracker.TrackRequest()
		resp, err := send(req)

		if resp != nil {
			transport.processRateLimitHeaders(resp)
		}

		return resp, err
	}
}

func (transport *rateLimitWrapper) processRateLimitHeaders(
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
