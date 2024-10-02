package clients

import (
	"math"
	"math/rand"
	"net/http"
	"strconv"
	"time"
)

// ExponentialBackoffWithJitter returns a duration to sleep for based on the
// attempt number, the minimum and maximum durations, and the response.
// If the response is nil or not a 429, the response is ignored.
// If the response is a 429, the Retry-After header is used to determine the
// duration to sleep for.
// Otherwise, the sleep duration is calculated as:
//
//	min * 2^(attemptNum)
//
// If the calculated duration is greater than max, max is used instead.
// A random jitter is added to the calculated duration, unless the calculated
// duration is >= max.
// The jitter is at most 25% of the calculated duration.
func ExponentialBackoffWithJitter(min, max time.Duration, attemptNum int, resp *http.Response) time.Duration {
	// based on go-retryablehttp's DefaultBackoff
	addJitter := func(duration time.Duration) time.Duration {
		jitter := SecondsToDuration(rand.Float64() * 0.25 * DurationToSeconds(duration))
		return duration + jitter
	}

	if resp != nil {
		if resp.StatusCode == http.StatusTooManyRequests {
			if s, ok := resp.Header["Retry-After"]; ok {
				if sleep, err := strconv.ParseFloat(s[0], 64); err == nil {
					// Add jitter in case of 429 status code
					return addJitter(SecondsToDuration(sleep))
				}
			}
		}
	}

	sleep := SecondsToDuration(math.Pow(2, float64(attemptNum)) * DurationToSeconds(min))

	// Add jitter to the general backoff calculation
	sleep = addJitter(sleep)

	if sleep > max {
		// at this point we've hit the max backoff, so just return that
		sleep = max
	}
	return sleep
}
