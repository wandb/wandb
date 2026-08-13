// Package api implements an enhanced HTTP client for wandb-core.
package api

import (
	"crypto/tls"
	"log/slog"
	"net/http"
	"net/url"
	"time"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/httplayers"
)

const (
	// Don't go slower than 1 request per 10 seconds.
	minRequestsPerSecond = 0.1

	// Don't go faster than 2^16 requests per second.
	//
	// This is an arbitrary limit that the client is never expected to hit.
	maxRequestsPerSecond = 65536

	// Don't send more than 10 requests at a time.
	maxBurst = 10

	// Default retry settings.
	DefaultRetryMax        = 20
	DefaultRetryWaitMin    = 2 * time.Second
	DefaultRetryWaitMax    = 60 * time.Second
	DefaultNonRetryTimeout = 30 * time.Second
)

// WBBaseURL is the address of the W&B backend, like https://api.wandb.ai.
type WBBaseURL *url.URL

// RetryableClient is an HTTP client with retries and special handling for W&B.
//
// The client is responsible for setting auth headers, retrying
// gracefully, and respecting rate-limit response headers.
type RetryableClient interface {
	// Sends an HTTP request with retries.
	//
	// There is special handling if the request is for the W&B backend.
	//
	// It is guaranteed that the response is non-nil unless there is an error.
	Do(*retryablehttp.Request) (*http.Response, error)
}

// clientImpl implements the RetryableClient interface.
type clientImpl struct {
	retryableHTTP RetryableClient // underlying HTTP client
	logger        *slog.Logger    // never nil
}

type ClientOptions struct {
	// Maximum number of retries to make for retryable requests.
	RetryMax int

	// Minimum time to wait between retries.
	RetryWaitMin time.Duration

	// Maximum time to wait between retries.
	RetryWaitMax time.Duration

	// Function that determines whether to retry based on the response.
	//
	// If nil, then retries are made on connection errors and server errors
	// (HTTP status code >=500).
	RetryPolicy retryablehttp.CheckRetry

	// Timeout for HTTP requests.
	//
	// This is the time to wait for an individual HTTP request to complete
	// before considering it as failed. It does not include retries: each retry
	// starts a new timeout.
	NonRetryTimeout time.Duration

	// Function that returns a proxy URL to use for a given http.Request.
	//
	// The proxy type is determined by the URL scheme.
	//
	// If the proxy URL contains a user info subcomponent,
	// the proxy request will pass the username and password
	// in a Proxy-Authorization header using the Basic scheme.
	//
	// If Proxy returns a non-nil error, the request is aborted with the error.
	//
	// If Proxy is nil or returns a nil *URL, no proxy will be used.
	Proxy func(*http.Request) (*url.URL, error)

	// ProxyConnectHeader configures headers sent to proxies during CONNECT
	// requests.
	//
	// This is often set to a Proxy-Authorization header, which is used to
	// authenticate with a proxy (separately from the target server).
	ProxyConnectHeader http.Header

	// Whether to disable SSL certificate verification.
	//
	// This is insecure and should only be used for testing/debugging
	// or in environments where the backend is trusted.
	InsecureDisableSSL bool

	// Function that gets called before the retry operation and prepares the
	// request for retry
	PrepareRetry func(*http.Request) error

	Logger *slog.Logger

	// PreRetryLayers specifies additional functionality to the HTTP client
	// that runs on every retry.
	PreRetryLayers httplayers.HTTPWrapper
}

// NewClient creates a new [RetryableClient].
//
// The client logs retries, is wboperation-aware, returns an enhanced RetryError
// with additional info when a retry is cancelled or times out, and sets
// the User-Agent header to "wandb-core".
func NewClient(opts ClientOptions) RetryableClient {
	if opts.RetryPolicy == nil {
		opts.RetryPolicy = retryablehttp.DefaultRetryPolicy
	}
	if opts.Logger == nil {
		opts.Logger = slog.New(slog.DiscardHandler)
	}

	retryableHTTP := retryablehttp.NewClient()
	retryableHTTP.HTTPClient.Transport = newRoundTripper(opts)
	retryableHTTP.Backoff = clients.ExponentialBackoffWithJitter
	retryableHTTP.RetryMax = opts.RetryMax
	retryableHTTP.RetryWaitMin = opts.RetryWaitMin
	retryableHTTP.RetryWaitMax = opts.RetryWaitMax
	retryableHTTP.HTTPClient.Timeout = opts.NonRetryTimeout
	retryableHTTP.PrepareRetry = opts.PrepareRetry
	retryableHTTP.CheckRetry = withRetryObservation(
		opts.RetryPolicy,
		opts.Logger,
	)

	// Let the client log debug messages.
	retryableHTTP.Logger = slog.NewLogLogger(
		opts.Logger.Handler(),
		slog.LevelDebug,
	)

	return &clientImpl{
		retryableHTTP: retryableHTTP,
		logger:        opts.Logger,
	}
}

func newRoundTripper(opts ClientOptions) http.RoundTripper {
	transport := &http.Transport{
		Proxy:              opts.Proxy,
		ProxyConnectHeader: opts.ProxyConnectHeader,
	}

	if opts.InsecureDisableSSL {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	userAgentHeader := make(http.Header, 1)
	userAgentHeader.Set("User-Agent", "wandb-core")

	return httplayers.WrapRoundTripper(transport, httplayers.Concat(
		// Add the User-Agent header only if it's not set by a preceding layer.
		httplayers.DefaultHeaders(userAgentHeader),
		opts.PreRetryLayers,
	))
}
