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
	logger        *slog.Logger
}

type ClientOptions struct {
	// BaseURL is the URL for the W&B server.
	BaseURL *url.URL

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

	// Additional headers to pass in each request to the backend.
	//
	// Note that these are only passed when communicating with the W&B backend.
	// In particular, they are not sent if using this client to send
	// arbitrary HTTP requests.
	ExtraHeaders map[string]string

	// Allows the client to peek at the network traffic, can perform any action
	// on the request and response. Need to make sure that the response body is
	// available to read by later stages.
	NetworkPeeker Peeker

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

	// Whether to disable SSL certificate verification.
	//
	// This is insecure and should only be used for testing/debugging
	// or in environments where the backend is trusted.
	InsecureDisableSSL bool

	// Adds credentials to http requests.
	CredentialProvider CredentialProvider

	// Function that gets called before the retry operation and prepares the
	// request for retry
	PrepareRetry func(*http.Request) error

	Logger *slog.Logger
}

// NewClient returns a new [RetryableClient] for making HTTP requests.
func NewClient(opts ClientOptions) RetryableClient {
	if opts.BaseURL == nil {
		panic("api: nil BaseURL")
	}

	retryableHTTP := retryablehttp.NewClient()
	retryableHTTP.Backoff = clients.ExponentialBackoffWithJitter
	retryableHTTP.RetryMax = opts.RetryMax
	retryableHTTP.RetryWaitMin = opts.RetryWaitMin
	retryableHTTP.RetryWaitMax = opts.RetryWaitMax
	retryableHTTP.HTTPClient.Timeout = opts.NonRetryTimeout
	retryableHTTP.PrepareRetry = opts.PrepareRetry

	// Set the retry policy with debug logging if possible.
	retryPolicy := opts.RetryPolicy
	if retryPolicy == nil {
		retryPolicy = retryablehttp.DefaultRetryPolicy
	}
	if opts.Logger != nil {
		retryPolicy = withRetryLogging(retryPolicy, opts.Logger)
	}
	retryableHTTP.CheckRetry = retryPolicy

	// Let the client log debug messages.
	if opts.Logger != nil {
		retryableHTTP.Logger = slog.NewLogLogger(
			opts.Logger.Handler(),
			slog.LevelDebug,
		)
	}

	// Set the Proxy function on the HTTP client.
	transport := &http.Transport{
		Proxy: opts.Proxy,
	}
	// Set the "Proxy-Authorization" header for the CONNECT requests
	// to the proxy server if the header is present in the extra headers.
	//
	// It is necessary if the proxy server uses TLS for the connection
	// and requires authentication using a scheme other than "Basic".
	if header := opts.ExtraHeaders["Proxy-Authorization"]; header != "" {
		transport.ProxyConnectHeader = http.Header{
			"Proxy-Authorization": []string{header},
		}
	}

	if opts.InsecureDisableSSL {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	extraHeaders := make(http.Header, len(opts.ExtraHeaders)+1)
	extraHeaders.Set("User-Agent", "wandb-core")
	for header, value := range opts.ExtraHeaders {
		extraHeaders.Set(header, value)
	}

	wandbOnlyLayers := httplayers.LimitTo(opts.BaseURL, httplayers.Concat(
		opts.CredentialProvider,
		httplayers.ExtraHeaders(extraHeaders),
		ResponseBasedRateLimiter(),
	))

	retryableHTTP.HTTPClient.Transport =
		httplayers.WrapRoundTripper(transport,
			httplayers.Concat(
				NetworkPeeker(opts.NetworkPeeker),
				wandbOnlyLayers,
			))

	return &clientImpl{
		retryableHTTP: retryableHTTP,
		logger:        opts.Logger,
	}
}
