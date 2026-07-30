package api

import (
	"context"
)

type retryObserverKey struct{}

// retryObserver tracks the errors retried by retryablehttp.
//
// It is only meant to be used during the execution of a single request,
// in a single goroutine, so it is not lock-protected.
type retryObserver struct {
	// lastRetriedError is a string representation of the most recently
	// retried error, if any.
	lastRetriedError string
}

// withRetryObserver returns a new context in which retried errors can be
// tracked.
func withRetryObserver(ctx context.Context) context.Context {
	return context.WithValue(ctx, retryObserverKey{}, &retryObserver{})
}

// setLastRetriedError records the most recent error being retried,
// if a retry observer is available.
func setLastRetriedError(ctx context.Context, desc string) {
	observer, ok := ctx.Value(retryObserverKey{}).(*retryObserver)
	if !ok {
		return
	}

	observer.lastRetriedError = desc
}

// lastRetriedError returns a description of the last error retried, if any,
// by the current HTTP request.
func lastRetriedError(ctx context.Context) string {
	observer, ok := ctx.Value(retryObserverKey{}).(*retryObserver)
	if !ok {
		return ""
	}

	return observer.lastRetriedError
}
