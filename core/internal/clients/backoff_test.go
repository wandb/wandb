package clients_test

import (
	"math"
	"net/http"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/clients"
)

func TestExponentialBackoffWithJitter_NonHTTP429(t *testing.T) {
	minimum := 1 * time.Second
	maximum := 10 * time.Second
	attemptNum := 3

	backoff := clients.ExponentialBackoffWithJitter(minimum, maximum, attemptNum, nil)

	// The expected range is between 2^3 * min and max.
	expectedMin := time.Duration(math.Pow(2, float64(attemptNum))) * minimum
	if expectedMin > maximum {
		expectedMin = maximum
	}

	assert.GreaterOrEqual(t, backoff, expectedMin, "Backoff should be greater than or equal to min")
	assert.LessOrEqual(t, backoff, maximum, "Backoff should be less than or equal to calculated max")
}

func TestExponentialBackoffWithJitter_HTTP429(t *testing.T) {
	minimum := 1 * time.Second
	maximum := 10 * time.Second
	retryAfter := 5 // seconds
	attemptNum := 1

	resp := &http.Response{
		StatusCode: http.StatusTooManyRequests,
		Header:     make(http.Header),
	}
	resp.Header.Set("Retry-After", strconv.Itoa(retryAfter))

	backoff := clients.ExponentialBackoffWithJitter(minimum, maximum, attemptNum, resp)

	// The expected range is between retryAfter and retryAfter + jitter.
	expectedMin := time.Duration(retryAfter) * time.Second
	expectedMax := expectedMin + time.Duration(0.25*float64(expectedMin))

	assert.GreaterOrEqual(
		t,
		backoff,
		expectedMin,
		"Backoff should be greater than or equal to Retry-After",
	)
	assert.LessOrEqual(
		t,
		backoff,
		expectedMax,
		"Backoff should be less than or equal to Retry-After plus jitter",
	)
}

func TestExponentialBackoffWithJitter_MaxBackoffLimit(t *testing.T) {
	minimum := 1 * time.Second
	maximum := 10 * time.Second
	attemptNum := 10 // High enough to exceed max

	backoff := clients.ExponentialBackoffWithJitter(minimum, maximum, attemptNum, nil)

	assert.LessOrEqual(t, backoff, maximum, "Backoff should not exceed max limit")
}
