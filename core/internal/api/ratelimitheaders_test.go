package api_test

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/api"
)

func Test_HeadersPresent(t *testing.T) {
	header := http.Header{}
	header.Set("RateLimit-Remaining", "123.5")
	header.Set("RateLimit-Reset", "9")

	result, ok := api.ParseRateLimitHeaders(header)

	assert.True(t, ok)
	assert.EqualValues(t, 123.5, result.Remaining)
	assert.EqualValues(t, 9, result.Reset)
}

func Test_RemainingInvalid(t *testing.T) {
	header := http.Header{}
	header.Set("RateLimit-Remaining", "oops")
	header.Set("RateLimit-Reset", "9")

	_, ok := api.ParseRateLimitHeaders(header)

	assert.False(t, ok)
}

func Test_RemainingNegative(t *testing.T) {
	header := http.Header{}
	header.Set("RateLimit-Remaining", "-4")
	header.Set("RateLimit-Reset", "9")

	_, ok := api.ParseRateLimitHeaders(header)

	assert.False(t, ok)
}

func Test_ResetInvalid(t *testing.T) {
	header := http.Header{}
	header.Set("RateLimit-Remaining", "123.5")
	header.Set("RateLimit-Reset", "oops")

	_, ok := api.ParseRateLimitHeaders(header)

	assert.False(t, ok)
}

func Test_ResetNegative(t *testing.T) {
	header := http.Header{}
	header.Set("RateLimit-Remaining", "123.5")
	header.Set("RateLimit-Reset", "-1")

	_, ok := api.ParseRateLimitHeaders(header)

	assert.False(t, ok)
}
