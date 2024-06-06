// W&B backend API.
package api

import (
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/pkg/observability"
)

const (
	// Don't go slower than 1 request per 10 seconds.
	//
	// If the server says to go slower than this, it's not your server. Run.
	minRequestsPerSecond = 0.1

	// Don't go faster than 2^10 requests per second.
	//
	// This is an arbitrary limit that the client is never expected to hit.
	// It's set low enough so that the rate limit estimation code can
	// converge quickly.
	maxRequestsPerSecond = 1024

	// Don't send more than 10 requests at a time.
	maxBurst = 10
)

// The W&B backend server.
//
// There is generally exactly one Backend and a small number of Clients in a
// process.
type Backend struct {
	// The URL prefix for all requests to the W&B API.
	baseURL *url.URL

	// The logger to use for HTTP-related logs.
	//
	// Note that these are only useful for debugging, and not helpful to a
	// user. There's no guarantee that all logs are made at the Debug level.
	logger *slog.Logger

	// A printer for writing to the user's console.
	printer *observability.Printer

	// API key for backend requests.
	apiKey string
}

// An HTTP client for interacting with the W&B backend.
//
// There is one Client per API provided by the backend, where "API" is a
// collection of related HTTP endpoints. It's expected that different APIs
// have different properties such as rate-limits and ideal retry behaviors.
//
// The client is responsible for setting auth headers, retrying
// gracefully, and respecting rate-limit response headers.
type Client interface {
	// Sends an HTTP request to the W&B backend.
	//
	// It is guaranteed that the response is non-nil unless there is an error.
	Send(*Request) (*http.Response, error)

	// Sends an arbitrary HTTP request.
	//
	// This is used for libraries that accept a custom HTTP client that they
	// then use to make requests to the backend, like GraphQL. If the request
	// URL matches the backend's base URL, there's special handling as in
	// Send().
	//
	// It is guaranteed that the response is non-nil unless there is an error.
	Do(*http.Request) (*http.Response, error)
}

type RetryableClient interface {
	Do(*retryablehttp.Request) (*http.Response, error)
}

// Implementation of the Client interface.
type clientImpl struct {
	// A reference to the backend.
	backend *Backend

	// The underlying retryable HTTP client.
	retryableHTTP RetryableClient

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

	// Additional HTTP headers to include in request.
	//
	// These are sent in addition to any headers set automatically by the
	// client, such as for auth. The client headers take precedence.
	Headers map[string]string
}

func (req *Request) String() string {
	return fmt.Sprintf(
		"Request{Method: %s, Path: %s, Body: %s, Headers: %v}",
		req.Method,
		req.Path,
		string(req.Body),
		req.Headers,
	)
}

type BackendOptions struct {
	// The scheme and hostname for contacting the server, not including a final
	// slash. For example, "http://localhost:8080".
	BaseURL *url.URL

	// Logger for HTTP operations.
	Logger *slog.Logger

	// A printer for sending feedback to the user.
	Printer *observability.Printer

	// W&B API key.
	APIKey string
}

// Creates a [Backend].
//
// The `baseURL` is the scheme and hostname for contacting the server, not
// including a final slash. Example "http://localhost:8080".
func New(opts BackendOptions) *Backend {
	// Fail early on missing parameters.
	switch {
	case opts.Logger == nil:
		panic("api: nil Logger not allowed")
	case opts.Printer == nil:
		panic("api: nil Printer not allowed")
	}

	return &Backend{
		baseURL: opts.BaseURL,
		logger:  opts.Logger,
		printer: opts.Printer,
		apiKey:  opts.APIKey,
	}
}

type ClientOptions struct {
	// A callback that runs on every HTTP response.
	NetworkPeeker Peeker

	// A human-readable string identifying the rate-limit used for this client.
	//
	// W&B has at least two independent rate limits: "filestream" and
	// "GraphQL". This string should help the user look up any limit they're
	// hitting in the documentation.
	RateLimitDomain string

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
}

// Creates a new [Client] for making requests to the [Backend].
func (backend *Backend) NewClient(opts ClientOptions) Client {
	if opts.RateLimitDomain == "" {
		panic("api: RateLimitDomain not set")
	}

	retryableHTTP := retryablehttp.NewClient()
	retryableHTTP.Backoff = clients.ExponentialBackoffWithJitter
	retryableHTTP.RetryMax = opts.RetryMax
	retryableHTTP.RetryWaitMin = opts.RetryWaitMin
	retryableHTTP.RetryWaitMax = opts.RetryWaitMax
	retryableHTTP.HTTPClient.Timeout = opts.NonRetryTimeout

	// Set the retry policy with debug logging if possible.
	retryPolicy := opts.RetryPolicy
	if retryPolicy == nil {
		retryPolicy = retryablehttp.DefaultRetryPolicy
	}
	if backend.logger != nil {
		retryPolicy = withRetryLogging(retryPolicy, backend.logger)
	}
	retryableHTTP.CheckRetry = retryPolicy

	// Let the client log debug messages.
	if backend.logger != nil {
		retryableHTTP.Logger = slog.NewLogLogger(
			backend.logger.Handler(),
			slog.LevelDebug,
		)
	}

	retryableHTTP.HTTPClient.Transport =
		NewPeekingTransport(
			opts.NetworkPeeker,
			NewRateLimitedTransport(
				opts.RateLimitDomain,
				retryableHTTP.HTTPClient.Transport,
				backend.printer))

	return &clientImpl{
		backend:       backend,
		retryableHTTP: retryableHTTP,
		extraHeaders:  opts.ExtraHeaders,
	}
}
