package api

import (
	"net/http"
	"strconv"
)

// Values of the RateLimit headers defined in
// https://www.ietf.org/archive/id/draft-polli-ratelimit-headers-02.html
type RateLimitHeaders struct {
	// The RateLimit-Remaining header.
	Remaining float64

	// The RateLimit-Reset header.
	Reset float64
}

// Parses RateLimitHeaders out of the HTTP header.
func ParseRateLimitHeaders(header http.Header) (RateLimitHeaders, bool) {
	rlRemaining, err := strconv.ParseFloat(header.Get("RateLimit-Remaining"), 64)
	if err != nil {
		return RateLimitHeaders{}, false
	}

	rlReset, err := strconv.ParseFloat(header.Get("RateLimit-Reset"), 64)
	if err != nil {
		return RateLimitHeaders{}, false
	}

	return RateLimitHeaders{
		Remaining: rlRemaining,
		Reset:     rlReset,
	}, true
}
