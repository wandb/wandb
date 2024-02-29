package clients

import (
	"log/slog"
	"time"

	"github.com/wandb/wandb/core/pkg/observability"

	"github.com/hashicorp/go-retryablehttp"
)

func SecondsToDuration(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
}

func DurationToSeconds(duration time.Duration) float64 {
	return float64(duration) / float64(time.Second)
}

func NewRetryClient(opts ...RetryClientOption) *retryablehttp.Client {
	retryClient := retryablehttp.NewClient()

	for _, opt := range opts {
		opt(retryClient)
	}
	return retryClient
}

type RetryClientOption func(rc *retryablehttp.Client)

func WithRetryClientLogger(logger *observability.CoreLogger) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.Logger = slog.NewLogLogger(logger.Logger.Handler(), slog.LevelDebug)
	}
}

func WithRetryClientRetryMax(retryMax int) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryMax = retryMax
	}
}

func WithRetryClientRetryWaitMin(retryWaitMin time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryWaitMin = retryWaitMin
	}
}

func WithRetryClientRetryWaitMax(retryWaitMax time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryWaitMax = retryWaitMax
	}
}

func WithRetryClientHttpTimeout(timeout time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.HTTPClient.Timeout = timeout
	}
}

func WithRetryClientRetryPolicy(retryPolicy retryablehttp.CheckRetry) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.CheckRetry = retryPolicy
	}
}

func WithRetryClientBackoff(backoff retryablehttp.Backoff) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.Backoff = backoff
	}
}
