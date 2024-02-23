// W&B backend API.
package api

import (
	"net/url"

	"github.com/hashicorp/go-retryablehttp"
)

// The W&B backend server.
//
// This models the server, in particular to handle rate limiting. There is
// generally exactly one Backend and a small number of Clients in a process.
type Backend struct {
	// The URL prefix for all requests to the W&B API.
	baseURL *url.URL
}

// An HTTP client for interacting with the W&B backend.
//
// Multiple Clients can be created for one Backend when different retry
// policies are needed.
//
// TODO: The client is responsible for setting auth headers, retrying
// gracefully, and respecting rate-limit response headers.
type Client struct {
	// A reference to the backend.
	backend *Backend

	// The underlying retryable HTTP client.
	retryableHTTP *retryablehttp.Client
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

// Creates a [Backend].
//
// The `baseURL` is the scheme and hostname for contacting the server, not
// including a final slash. Example "http://localhost:8080".
func New(baseURL *url.URL) *Backend {
	return &Backend{baseURL}
}

// Creates a new [Client] for making requests to the [Backend].
//
// TODO: For now this accepts a [retryablehttp.Client] directly, but it will
// be rewritten to accept a list of specific options instead. Do not rely on
// having a reference to the underlying client.
func (backend *Backend) NewClient(retryableHTTP *retryablehttp.Client) *Client {
	return &Client{
		backend:       backend,
		retryableHTTP: retryableHTTP,
	}
}
