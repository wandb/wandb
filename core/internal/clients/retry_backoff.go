package clients

import (
	"math"
	"math/rand"
	"net/http"
	"strconv"
	"time"
)

func ExponentialBackoffWithJitter(min, max time.Duration, attemptNum int, resp *http.Response) time.Duration {
	// based on go-retryablehttp's DefaultBackoff
	addJitter := func(duration time.Duration) time.Duration {
		jitter := time.Duration(rand.Float64() * 0.25 * float64(duration))
		return duration + jitter
	}

	if resp != nil {
		if resp.StatusCode == http.StatusTooManyRequests {
			if s, ok := resp.Header["Retry-After"]; ok {
				if sleep, err := strconv.ParseInt(s[0], 10, 64); err == nil {
					// Add jitter in case of 429 status code
					return addJitter(time.Second * time.Duration(sleep))
				}
			}
		}
	}

	mult := math.Pow(2, float64(attemptNum)) * float64(min)
	sleep := time.Duration(mult)

	// Add jitter to the general backoff calculation
	sleep = addJitter(sleep)

	if float64(sleep) != mult || sleep > max {
		// at this point we've hit the max backoff, so just return that
		sleep = max
	}
	return sleep
}
