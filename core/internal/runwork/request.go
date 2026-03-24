package runwork

import (
	"context"
	"sync/atomic"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Request is a ServerRequest for a run that requires a response.
//
// This should not be used outside for anything unrelated to runwork.
//
// A non-nil Request requires a response unless it is cancelled, or else
// a context leak occurs. It is good practice to call WillNotRespond on any
// Request value (whether or not it is nil) in codepaths where a response
// is not expected. WillNotRespond raises an error on the client if it was
// awaiting a response.
//
// Since many ServerRequests don't require a response (like history updates),
// is it OK to assume Request is nil on their codepaths and not do anything
// with it. This risks creating a context leak if the client asks for
// a response, but in that case, the client will hang while waiting for it.
type Request struct {
	requestID string // the ServerRequest's request_id

	ctx       context.Context
	cancelCtx context.CancelFunc

	responded  atomic.Bool // makes Respond() a no-op after the first call
	responseCh chan<- *spb.ServerResponse
}

// NewRequest creates a request.
//
// The context defines the request's lifetime. If it is cancelled before
// a response is produced, that means that a response is no longer needed.
//
// When the request gets a response, it is pushed to responseCh
// and the context cancellation function is invoked.
//
// The caller must guarantee that the request is not responded to after
// responseCh is closed. In practice, that means waiting for all goroutines
// with a reference to the Request to exit, probably via a WaitGroup.
func NewRequest(
	requestID string,
	ctx context.Context,
	cancelCtx context.CancelFunc,
	responseCh chan<- *spb.ServerResponse,
) *Request {
	return &Request{
		requestID:  requestID,
		ctx:        ctx,
		cancelCtx:  cancelCtx,
		responseCh: responseCh,
	}
}

// Context is cancelled when the Request is cancelled or responded to.
//
// Panics if the request is nil.
//
// This Context must only be used for operations that are needed for
// producing a response, since once a response is produced, all operations
// using this Context get cancelled.
//
// This should usually be coupled with ExtraWork.BeforeEndCtx() using
//
//	cleanup := beforeEndCtx.AfterFunc(request.WillNotRespond)
//	defer cleanup()
//
// to terminate the request if the stream is shutting down.
func (r *Request) Context() context.Context {
	if r == nil {
		panic("runwork: nil Request has no Context")
	}

	return r.ctx
}

// Respond responds to the request and cancels its Context.
//
// This sets the request ID on the response.
// Responses after the first one are ignored.
// Safe to call in multiple goroutines simultaneously.
//
// If the request is already cancelled, this does nothing.
//
// For convenience, this may be called on a nil Request, in which case it is
// a no-op.
func (r *Request) Respond(response *spb.ServerResponse) {
	if r == nil {
		return
	}

	if r.responded.Swap(true) {
		return
	}

	defer r.cancelCtx()

	response.RequestId = r.requestID

	select {
	case r.responseCh <- response:
	case <-r.ctx.Done():
	}
}

// WillNotRespond responds to the request with a "no response" error.
//
// A function that receives a Request and neither passes it anywhere nor
// responds to it should generally call this. This is used for Records
// where a response is not expected or if a function is cancelled.
//
// This raises an error on the client side if the client expected a response.
//
// For convenience, this may be called on a nil Request, in which case it is
// a no-op.
func (r *Request) WillNotRespond() {
	r.Respond(&spb.ServerResponse{
		ServerResponseType: &spb.ServerResponse_ErrorResponse{
			ErrorResponse: &spb.ServerErrorResponse{
				Message: "No response.",
			},
		},
	})
}
