package clients

import (
	"math"
	"math/rand"
	"net/http"
	"strconv"
	"time"
)

// ExponentialBackoffWithJitter returns a duration to wait before retrying.
//
// If the response has a valid Retry-After header, its value is returned.
// Otherwise, this calculates an exponential backoff from the attempt number:
//
//	minimum * 2^attemptNum
//
// The attempt number is zero-based, like in hashichorp/go-retryablehttp.
//
// A random jitter of up to 25% the calculated duration is added and the result
// is clamped to the given maximum.
func ExponentialBackoffWithJitter(
	minimum, maximum time.Duration,
	attemptNum int,
	resp *http.Response,
) time.Duration {
	retryAfter := retryAfterHeader(resp)
	if retryAfter >= 0 {
		return retryAfter
	}

	// Limit to a 2^32 multiplier to avoid precision/overflow issues.
	attemptNum = min(attemptNum, 32)

	jitterMult := 1 + 0.25*rand.Float64()
	backoffMult := math.Pow(2, float64(attemptNum))
	backoff := seconds(jitterMult * backoffMult * minimum.Seconds())

	return min(maximum, backoff)
}

// retryAfterHeader returns the Retry-After header from the response, or a
// negative value if there's no response or no valid header.
func retryAfterHeader(resp *http.Response) time.Duration {
	if resp == nil {
		return -1
	}

	header, ok := resp.Header["Retry-After"]
	if !ok || len(header) != 1 {
		return -1
	}

	// Like "Retry-After: 120"
	retryAfterSec, err := strconv.ParseFloat(header[0], 64)
	if err == nil { // if NO error
		return seconds(retryAfterSec)
	}

	// Like "Retry-After: Fri, 31 Dec 1999 23:59:59 GMT"
	retryAfterTime, err := time.Parse(time.RFC1123, header[0])
	if err == nil { // if NO error
		return max(0, time.Until(retryAfterTime))
	}

	// According to RFC 9110, a client must also accept two obsolete formats:
	// 	Sunday, 06-Nov-94 08:49:37 GMT   ; obsolete RFC 850 format
	//  Sun Nov  6 08:49:37 1994         ; ANSI C's asctime() format
	// But since we control the backend, we do not do this.

	return -1
}

// seconds returns the number of seconds as a time.Duration.
func seconds(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
}
