package api

import (
	"context"
	"net/http"
)

const (
	// ServerHeader is the header the W&B server sets on every response.
	//
	// A response without it may have come from something in front of the
	// server, like a load balancer, ingress or proxy. It can also come from a
	// server release that predates the header, a proxy that strips it, or
	// Go's HTTP server rejecting a malformed request before the W&B handler
	// runs. Its absence is evidence of origin, not proof.
	//
	// The server advertises that it sends the header through the
	// RESPONSE_ORIGIN_HEADER server feature.
	ServerHeader = "X-Wandb-Server"

	// ServerHeaderValue is the value of ServerHeader on W&B server responses.
	ServerHeaderValue = "gorilla"
)

// HasServerHeader reports whether the W&B server marked the response
// with ServerHeader.
func HasServerHeader(resp *http.Response) bool {
	return resp != nil && resp.Header.Get(ServerHeader) == ServerHeaderValue
}

type responseObserverKey struct{}

// WithResponseObserver returns a context in which RetryableClient.Do passes
// the final response of a request, after any retries, to observe.
//
// This lets code that only sees a higher-level client, like a GraphQL client,
// inspect the HTTP response headers.
//
// observe runs in the goroutine that called Do, before Do returns. It must not
// read or close the response body. It is not called if Do returns an error.
func WithResponseObserver(
	ctx context.Context,
	observe func(*http.Response),
) context.Context {
	return context.WithValue(ctx, responseObserverKey{}, observe)
}

// observeResponse passes resp to the context's response observer, if any.
func observeResponse(ctx context.Context, resp *http.Response) {
	observe, ok := ctx.Value(responseObserverKey{}).(func(*http.Response))
	if ok && observe != nil {
		observe(resp)
	}
}
