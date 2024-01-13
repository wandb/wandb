package retryableclient

import (
	"encoding/base64"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/observability"
)

func basicAuth(username, password string) string {
	auth := username + ":" + password
	return base64.StdEncoding.EncodeToString([]byte(auth))
}

// combineHeaders converts a slice of maps to a single map
func combineHeaders(headers ...map[string]string) map[string]string {
	result := make(map[string]string)
	for _, h := range headers {
		for k, v := range h {
			result[k] = v
		}
	}
	return result
}

type authedTransport struct {
	key     string
	headers map[string]string
	wrapped http.RoundTripper
}

func getResponseLogHook(logger *slog.Logger, logResponse func(resp *http.Response) bool) func(logger retryablehttp.Logger, resp *http.Response) {
	return func(_ retryablehttp.Logger, resp *http.Response) {
		if logResponse != nil && !logResponse(resp) {
			return
		}
		body, err := io.ReadAll(resp.Body)
		if err == nil {
			logger.Info("HTTP Error", "status", resp.StatusCode, "body", string(body))
		}
	}
}

func (t *authedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	req.Header.Set("User-Agent", "wandb-core")
	for k, v := range t.headers {
		req.Header.Set(k, v)
	}
	return t.wrapped.RoundTrip(req)
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

func WithRetryClientHttpTransport(transport http.RoundTripper) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.HTTPClient.Transport = transport
	}
}

func WithRetryClientHttpAuthTransport(key string, headers ...map[string]string) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.HTTPClient.Transport = &authedTransport{
			key:     key,
			headers: combineHeaders(headers...),
			wrapped: rc.HTTPClient.Transport,
		}
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

// WithRetryClientResponseLogger is an option to NewRetryClient allowing responses to be logged.
// logger is an slog.Logger to use for logging, logResponse is a function to determine if the response
// should be logged.
func WithRetryClientResponseLogger(logger *slog.Logger, logResponse func(resp *http.Response) bool) RetryClientOption {
	// TODO: should we also add a logRequest function?
	return func(rc *retryablehttp.Client) {
		rc.ResponseLogHook = getResponseLogHook(logger, logResponse)
	}
}
