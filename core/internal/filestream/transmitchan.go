package filestream

import (
	"time"

	"github.com/wandb/wandb/core/internal/waiting"
)

// TransmitChan is a channel of FileStreamRequestJSON values.
//
// It is designed to be read by one goroutine and written to by another.
//
// The key difference from a regular channel is that the writing goroutine
// can detect if a value would be accepted before creating it. This is important
// because creating the FileStreamRequestJSON object is expensive.
type TransmitChan struct {
	// requests is a 1-buffered channel of added requests.
	//
	// It is 1-buffered to maintain the non-blocking guarantee of `ready`.
	// See the logic in NextRequest.
	requests chan *FileStreamRequestJSON

	// ready is a 1-buffered channel that indicates when a single
	// request can be pushed without blocking.
	//
	// When `requests` can accept a value without blocking, it is added
	// to the `ready` channel.
	ready chan chan<- *FileStreamRequestJSON
}

func NewTransmitChan() *TransmitChan {
	return &TransmitChan{
		requests: make(chan *FileStreamRequestJSON, 1),
		ready:    make(chan chan<- *FileStreamRequestJSON, 1),
	}
}

// NextRequest returns the next request to make or a heartbeat
// if enough time has passed.
//
// If the channel is closed, returns (nil, false).
// Otherwise, returns a non-nil value and true.
func (tc *TransmitChan) NextRequest(heartbeat waiting.Stopwatch) (
	*FileStreamRequestJSON,
	bool,
) {
	// Mark ready if not marked yet.
	//
	// If tc.requests has a buffered item, we're about to pop it and empty
	// a buffer slot. If it does not, then it already has an empty buffer slot.
	select {
	case tc.ready <- tc.requests:
	default:
	}

	// Return a request if one is already available.
	select {
	case x, ok := <-tc.requests:
		return x, ok
	default:
	}

	// Otherwise, wait for a request or a heartbeat.
	heartbeatCh, heartbeatCancel := heartbeat.Wait()
	select {
	case x, ok := <-tc.requests:
		heartbeatCancel()
		return x, ok

	case <-heartbeatCh:
		return &FileStreamRequestJSON{}, true
	}
}

// PreparePush returns a channel to which to push the next request.
//
// Exactly one value must be pushed into the returned channel.
// Pushing to the request channel is guaranteed not to block.
func (tc *TransmitChan) PreparePush() <-chan (chan<- *FileStreamRequestJSON) {
	return tc.ready
}

// Push blocks until it can push a request.
//
// It is shorthand for using PreparePush and adding to the returned channel.
func (tc *TransmitChan) Push(request *FileStreamRequestJSON) {
	pushChan := <-tc.PreparePush()
	pushChan <- request
}

// IgnoreFutureRequests causes all new requests to be ignored.
//
// It effectively closes the read-side of the channel.
func (tc *TransmitChan) IgnoreFutureRequests() {
	// This goroutine gets garbage collected after Close() is called.
	go func() {
		for {
			_, ok := tc.NextRequest(waiting.NewStopwatch(time.Hour))
			if !ok {
				return
			}
		}
	}()
}

// Close indicates no more requests will be pushed.
func (tc *TransmitChan) Close() {
	close(tc.requests)
}
