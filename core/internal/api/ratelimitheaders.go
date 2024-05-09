package api

import (
	"net/http"
	"strconv"
)

// Values of the RateLimit headers defined in
// https://www.ietf.org/archive/id/draft-polli-ratelimit-headers-02.html
type RateLimitHeaders struct {
	// The RateLimit-Remaining header.
	//
	// Guaranteed non-negative.
	Remaining float64

	// The RateLimit-Reset header.
	//
	// Guaranteed non-negative.
	Reset float64
}

// Parses RateLimitHeaders out of the HTTP header.
func ParseRateLimitHeaders(header http.Header) (RateLimitHeaders, bool) {
	headers := RateLimitHeaders{}

	remainingStr := header.Get("RateLimit-Remaining")
	resetStr := header.Get("RateLimit-Reset")

	if remainingStr != "" && resetStr != "" {
		remaining, err := strconv.ParseFloat(remainingStr, 64)
		if err != nil || remaining < 0 {
			return RateLimitHeaders{}, false
		}

		reset, err := strconv.ParseFloat(resetStr, 64)
		if err != nil || reset < 0 {
			return RateLimitHeaders{}, false
		}

		headers.Remaining = remaining
		headers.Reset = reset
		return headers, true
	}

	// legacy entity level rate limit headers
	legacyRemainingStr := header.Get("X-RateLimit-Remaining")
	if legacyRemainingStr != "" {
		remaining, err := strconv.ParseFloat(legacyRemainingStr, 64)
		if err != nil || remaining < 0 {
			return RateLimitHeaders{}, false
		}

		headers.Remaining = remaining
		// legacy rate limit doesn't send back a reset time
		headers.Reset = 0
		return headers, true
	}

	return RateLimitHeaders{}, false
}


