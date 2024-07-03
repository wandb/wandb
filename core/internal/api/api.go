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

	// W&B API key.
	APIKey string
}

// Creates a [Backend].
//
// The `baseURL` is the scheme and hostname for contacting the server, not
// including a final slash. Example "http://localhost:8080".
func New(opts BackendOptions) *Backend {
	return &Backend{
		baseURL: opts.BaseURL,
		logger:  opts.Logger,
		apiKey:  opts.APIKey,
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

	// Additional headers to pass in each request to the backend.
	//
	// Note that these are only passed when communicating with the W&B backend.
	// In particular, they are not sent if using this client to send
	// arbitrary HTTP requests.
	ExtraHeaders map[string]string

	// Allows the client to peek at the network traffic, can preform any action
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
}

// Creates a new [Client] for making requests to the [Backend].
func (backend *Backend) NewClient(opts ClientOptions) Client {
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

	retryableHTTP.HTTPClient.Transport =
		NewPeekingTransport(
			opts.NetworkPeeker,
			NewRateLimitedTransport(transport),
		)

	return &clientImpl{
		backend:       backend,
		retryableHTTP: retryableHTTP,
		extraHeaders:  opts.ExtraHeaders,
	}
}
