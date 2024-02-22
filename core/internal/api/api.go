// W&B backend API.
package api

import (
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
)

// The W&B backend server.
//
// This models the server, in particular to handle rate limiting. There is
// generally exactly one Backend and a small number of Clients in a process.
type Backend struct {
	// The URL prefix for all requests to the W&B API.
	baseURL *url.URL

	// The logger to use for debug information.
	logger *slog.Logger

	// API key for backend requests.
	apiKey string
}

// An HTTP client for interacting with the W&B backend.
//
// Multiple Clients can be created for one Backend when different retry
// policies are needed.
//
// TODO: The client is responsible for setting auth headers, retrying
// gracefully, and respecting rate-limit response headers.
type Client interface {
	// Sends an HTTP request to the W&B backend.
	Send(*Request) (*http.Response, error)
}

// Implementation of the Client interface.
type clientImpl struct {
	// A reference to the backend.
	backend *Backend

	// The underlying retryable HTTP client.
	retryableHTTP *retryablehttp.Client

	// Headers to pass in every request.
	extraHeaders map[string]string
}

// An HTTP request to the W&B backend.
type Request struct {
	// The standard HTTP method.
	Method string

	// The request path, not including the scheme or hostname.
	//
	// Example: "/files/a/b/c/file_stream".
	Path string

	// The request body or nil.
	//
	// Since requests may be retried, this is always a byte slice rather than
	// an [io.ReadCloser] as in Go's standard HTTP package.
	Body []byte

	// Additional HTTP headers to include in the request.
	//
	// These are sent in addition to any headers set automatically by the
	// client, such as for auth. The client headers take precedence.
	Headers map[string]string
}

type BackendOptions struct {
	// The scheme and hostname for contacting the server, not including a final
	// slash. For example, "http://localhost:8080".
	BaseURL *url.URL

	// Logger for HTTP operations.
	Logger *slog.Logger

	// W&B API key.
	APIKey string
}

// Creates a [Backend].
//
// The `baseURL` is the scheme and hostname for contacting the server, not
// including a final slash. Example "http://localhost:8080".
func New(opts BackendOptions) *Backend {
	return &Backend{
		opts.BaseURL,
		opts.Logger,
		opts.APIKey,
	}
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

	// Additional headers to pass in each request.
	ExtraHeaders map[string]string
}

// Creates a new [Client] for making requests to the [Backend].
func (backend *Backend) NewClient(opts ClientOptions) Client {
	retryableHTTP := clients.NewRetryClient(
		clients.WithRetryClientBackoff(clients.ExponentialBackoffWithJitter),
		clients.WithRetryClientRetryMax(opts.RetryMax),
		clients.WithRetryClientRetryWaitMin(opts.RetryWaitMin),
		clients.WithRetryClientRetryWaitMax(opts.RetryWaitMax),
		clients.WithRetryClientHttpTimeout(opts.NonRetryTimeout),
	)

	if opts.RetryPolicy != nil {
		retryableHTTP.CheckRetry = opts.RetryPolicy
	}

	if backend.logger != nil {
		retryableHTTP.ResponseLogHook = hookLogErrors(backend.logger)
		retryableHTTP.Logger = slog.NewLogLogger(
			backend.logger.Handler(),
			slog.LevelDebug,
		)
	}

	return &clientImpl{backend, retryableHTTP, opts.ExtraHeaders}
}

// Returns a hook that logs all HTTP error responses.
func hookLogErrors(logger *slog.Logger) retryablehttp.ResponseLogHook {
	return func(_ retryablehttp.Logger, response *http.Response) {
		if response.StatusCode < 400 {
			return
		}

		body, err := io.ReadAll(response.Body)
		if err != nil {
			logger.Error(
				"HTTP Error",
				"status", response.StatusCode,
				"body", string(body),
			)
		}
	}
}
