package filestream

import (
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/time/rate"
)

// CollectLoop batches changes together to make filestream requests.
//
// This batches all incoming requests while waiting for transmissions
// to go through.
type CollectLoop struct {
	Logger              *observability.CoreLogger
	TransmitRateLimit   *rate.Limiter
	MaxRequestSizeBytes int
}

// Start ingests requests and outputs rate-limited, batched requests.
func (cl CollectLoop) Start(
	state *FileStreamState,
	requests <-chan *FileStreamRequest,
) *TransmitChan {
	output := NewTransmitChan()

	go func() {
		buffer := &FileStreamRequest{}
		hasMore := true

		for request := range requests {
			buffer.Merge(request)

			cl.waitForRateLimit(state, buffer, requests)
			hasMore = cl.transmit(state, buffer, requests, output)
		}

		for hasMore {
			var json *FileStreamRequestJSON
			json, hasMore = state.Pop(buffer, cl.MaxRequestSizeBytes)
			output.Push(json)
		}

		output.Close()
	}()

	return output
}

// waitForRateLimit merges requests until the rate limit allows us
// to transmit data.
func (cl CollectLoop) waitForRateLimit(
	state *FileStreamState,
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
) {
	if cl.shouldSendASAP(state, buffer) {
		return
	}

	reservation := cl.TransmitRateLimit.Reserve()

	// If we would be rate-limited forever, just ignore the limit.
	if !reservation.OK() {
		return
	}

	for {
		timer := time.NewTimer(reservation.Delay())
		select {
		case <-timer.C:
			return

		case request, ok := <-requests:
			_ = timer.Stop()

			if !ok {
				return
			}

			buffer.Merge(request)

			if cl.shouldSendASAP(state, buffer) {
				return
			}
		}
	}
}

// transmit accumulates incoming requests until a transmission goes through.
//
// Returns whether there remains unsent data in the buffer.
func (cl CollectLoop) transmit(
	state *FileStreamState,
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
	output *TransmitChan,
) bool {
	for {
		// If we're at max size, stop adding to the buffer.
		if state.IsAtSizeLimit(buffer, cl.MaxRequestSizeBytes) {
			cl.Logger.Info("filestream: waiting to send request of max size")
			json, hasMore := state.Pop(buffer, cl.MaxRequestSizeBytes)
			output.Push(json)
			return hasMore
		}

		// Otherwise, either send the buffer or add to it.
		select {
		case pushChan := <-output.PreparePush():
			json, hasMore := state.Pop(buffer, cl.MaxRequestSizeBytes)
			pushChan <- json
			return hasMore

		case request, ok := <-requests:
			if !ok {
				json, hasMore := state.Pop(buffer, cl.MaxRequestSizeBytes)
				output.Push(json)
				return hasMore
			}

			buffer.Merge(request)
		}
	}
}

// shouldSendASAP returns a request should be made regardless of rate limits.
func (cl CollectLoop) shouldSendASAP(
	state *FileStreamState,
	request *FileStreamRequest,
) bool {
	switch {
	// Send the "pre-empting" state immediately.
	//
	// This state indicates that the process may be about to yield the
	// CPU for an unknown amount of time, and we want to let the backend
	// know ASAP.
	case request.Preempting:
		return true

	// If we've accumulated a request of the maximum size, send it immediately.
	case state.IsAtSizeLimit(request, cl.MaxRequestSizeBytes):
		return true

	default:
		return false
	}
}
