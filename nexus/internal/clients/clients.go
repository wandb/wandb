package clients

import (
	"encoding/base64"
	"log/slog"
	"net/http"
	"time"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/hashicorp/go-retryablehttp"
)

func basicAuth(username, password string) string {
	auth := username + ":" + password
	return base64.StdEncoding.EncodeToString([]byte(auth))
}

type authedTransport struct {
	key     string
	wrapped http.RoundTripper
}

func (t *authedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	req.Header.Set("User-Agent", "wandb-nexus")
	return t.wrapped.RoundTrip(req)
}

type authedTransportWithHeaders struct {
	key      string
	username string
	email    string
	wrapped  http.RoundTripper
	headers  map[string]string
}

func (t *authedTransportWithHeaders) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	req.Header.Set("User-Agent", "wandb-nexus")
	req.Header.Set("X-WANDB-USERNAME", t.username)
	req.Header.Set("X-WANDB-USER-EMAIL", t.email)
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

func WithRetryClientLogger(logger *observability.NexusLogger) RetryClientOption {
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

func WithRetryClientHttpAuthTransport(key string) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.HTTPClient.Transport = &authedTransport{
			key:     key,
			wrapped: rc.HTTPClient.Transport,
		}
	}
}

func WithRetryClientHttpAuthTransportWithHeaders(key, username, email string, headers map[string]string) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		authTransport := &authedTransportWithHeaders{
			key:      key,
			username: username,
			email:    email,
			wrapped:  rc.HTTPClient.Transport,
			headers:  headers,
		}
		rc.HTTPClient.Transport = authTransport
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
