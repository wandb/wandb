package clients_test

import (
	"net/http"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/clients"
)

func TestExponentialBackoffWithJitter(t *testing.T) {
	// The target backoff will be 1s * 2^4 = 16s.
	// A 25% jitter is 4s, so the result will be between 16s and 20s,
	// but clamping to the maximum limits the range to 16s - 19s.
	minimum := 1 * time.Second
	maximum := 19 * time.Second
	attemptNum := 4

	minBackoffSec := +123.4
	maxBackoffSec := -123.4
	for range 100 {
		backoff := clients.ExponentialBackoffWithJitter(
			minimum, maximum, attemptNum, nil)

		minBackoffSec = min(backoff.Seconds(), minBackoffSec)
		maxBackoffSec = max(backoff.Seconds(), maxBackoffSec)
	}

	assert.IsNonDecreasing(t, []float64{16, minBackoffSec, maxBackoffSec, 19})

	// Values chosen for a near 0% chance of failing.
	assert.LessOrEqual(t, minBackoffSec, 16.5)
	assert.GreaterOrEqual(t, maxBackoffSec, 18.99)
}

func TestExponentialBackoffWithJitter_RetryAfter_Seconds(t *testing.T) {
	minimum := 1 * time.Second
	maximum := 10 * time.Second
	attemptNum := 1

	resp := &http.Response{Header: make(http.Header)}
	resp.Header.Set("Retry-After", "5")

	backoff := clients.ExponentialBackoffWithJitter(
		minimum, maximum, attemptNum, resp)

	assert.Exactly(t, 5*time.Second, backoff)
}

func TestExponentialBackoffWithJitter_RetryAfter_Date(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		minimum := 1 * time.Second
		maximum := 10 * time.Second
		attemptNum := 1

		nowPlus3Seconds := time.Now().Add(3 * time.Second)
		resp := &http.Response{Header: make(http.Header)}
		resp.Header.Set("Retry-After", nowPlus3Seconds.Format(time.RFC1123))

		backoff := clients.ExponentialBackoffWithJitter(
			minimum, maximum, attemptNum, resp)

		assert.Exactly(t, 3*time.Second, backoff)
	})
}

func TestExponentialBackoffWithJitter_RetryAfter_PastDate(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		minimum := 1 * time.Second
		maximum := 10 * time.Second
		attemptNum := 1

		nowMinus3Seconds := time.Now().Add(-3 * time.Second)
		resp := &http.Response{Header: make(http.Header)}
		resp.Header.Set("Retry-After", nowMinus3Seconds.Format(time.RFC1123))

		backoff := clients.ExponentialBackoffWithJitter(
			minimum, maximum, attemptNum, resp)

		assert.Exactly(t, time.Duration(0), backoff)
	})
}

func TestExponentialBackoffWithJitter_Overflow(t *testing.T) {
	minimum := 1 * time.Second
	maximum := 10 * time.Second
	attemptNum := 100_000 // math.Pow(2, 100_000) is +Inf

	backoff := clients.ExponentialBackoffWithJitter(
		minimum, maximum, attemptNum, nil)

	assert.Exactly(t, maximum, backoff)
}
