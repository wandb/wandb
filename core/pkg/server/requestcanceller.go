package server

import (
	"context"
	"log/slog"
	"sync"
)

// RequestCanceller manages contexts for cancellable requests to wandb-core.
type RequestCanceller struct {
	mu sync.Mutex

	// requestCtxCancel maps some active server request IDs to functions
	// that can be used to cancel their operations.
	requestCtxCancel map[string]func()
}

func NewRequestCanceller() *RequestCanceller {
	return &RequestCanceller{
		requestCtxCancel: make(map[string]func()),
	}
}

// Context returns a new cancellable context for the given request ID
// along with its cancellation function.
//
// The caller must cancel the context, or else a context leak will occur.
// A context leak is a goroutine leak; enough of these can crash the program,
// so it's important to make designs that support a `defer cancel()`.
//
// If the request ID is empty, this returns a background context and a no-op
// cancellation function. If a previous request's ID is given, an error is
// logged and a background context is returned.
func (rc *RequestCanceller) Context(id string) (context.Context, func()) {
	if id == "" {
		return context.Background(), func() {}
	}

	rc.mu.Lock()
	defer rc.mu.Unlock()

	if _, exists := rc.requestCtxCancel[id]; exists {
		slog.Error("requestcanceller: request ID already exists", "id", id)
		return context.Background(), func() {}
	}

	ctx, cancel := context.WithCancel(context.Background())
	rc.requestCtxCancel[id] = cancel

	// Clear the map once the context is cancelled.
	context.AfterFunc(ctx, func() {
		rc.mu.Lock()
		defer rc.mu.Unlock()
		delete(rc.requestCtxCancel, id)
	})

	return ctx, cancel
}

// Cancel cancels the context for a previously registered request.
func (rc *RequestCanceller) Cancel(id string) {
	rc.mu.Lock()
	defer rc.mu.Unlock()

	cancel, ok := rc.requestCtxCancel[id]
	if !ok {
		// Already cancelled, or wasn't cancellable.
		return
	}

	cancel()
}
