package httplayerstest

import (
	"net/http"
	"slices"
	"sync"

	"github.com/wandb/wandb/core/internal/httplayers"
)

// HTTPWrapperRecorder wraps an HTTPDoFunc in a layer that records calls
// made to it.
type HTTPWrapperRecorder struct {
	mu    sync.Mutex
	calls []*http.Request
}

// NewHTTPWrapperRecorder creates a new HTTPWrapperRecorder.
func NewHTTPWrapperRecorder() *HTTPWrapperRecorder {
	return &HTTPWrapperRecorder{}
}

// Calls returns the *http.Request values collected from calls to the recorder.
func (r *HTTPWrapperRecorder) Calls() []*http.Request {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Clone(r.calls)
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (r *HTTPWrapperRecorder) WrapHTTP(
	send httplayers.HTTPDoFunc,
) httplayers.HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		r.mu.Lock()
		r.calls = append(r.calls, req)
		r.mu.Unlock()

		return send(req)
	}
}
