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
		isDone := false

		for request := range requests {
			buffer.Merge(request)

			cl.waitForRateLimit(buffer, requests)
			buffer, isDone = cl.transmit(state, buffer, requests, output)
		}

		for !isDone {
			reader, _ := NewRequestReader(buffer, cl.MaxRequestSizeBytes)
			output.Push(reader.GetJSON(state, cl.Logger))
			buffer, isDone = reader.Next()
		}

		output.Close()
	}()

	return output
}

// waitForRateLimit merges requests until the rate limit allows us
// to transmit data.
func (cl CollectLoop) waitForRateLimit(
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
) {
	if cl.shouldSendASAP(buffer) {
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

			if cl.shouldSendASAP(buffer) {
				return
			}
		}
	}
}

// transmit accumulates incoming requests until a transmission goes through.
func (cl CollectLoop) transmit(
	state *FileStreamState,
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
	output *TransmitChan,
) (*FileStreamRequest, bool) {
	for {
		reader, isTruncated := NewRequestReader(buffer, cl.MaxRequestSizeBytes)

		// If we're at max size, stop adding to the buffer.
		if isTruncated {
			cl.Logger.Info("filestream: waiting to send request of max size")
			output.Push(reader.GetJSON(state, cl.Logger))
			return reader.Next()
		}

		// Otherwise, either send the buffer or add to it.
		select {
		case pushChan := <-output.PreparePush():
			pushChan <- reader.GetJSON(state, cl.Logger)
			return reader.Next()

		case request, ok := <-requests:
			if !ok {
				output.Push(reader.GetJSON(state, cl.Logger))
				return reader.Next()
			}

			buffer.Merge(request)
		}
	}
}

// shouldSendASAP returns a request should be made regardless of rate limits.
func (cl CollectLoop) shouldSendASAP(request *FileStreamRequest) bool {
	_, isTruncated := NewRequestReader(request, cl.MaxRequestSizeBytes)

	switch {
	// If we've accumulated a request of the maximum size, send it immediately.
	case isTruncated:
		return true

	// Send the "pre-empting" state immediately.
	//
	// This state indicates that the process may be about to yield the
	// CPU for an unknown amount of time, and we want to let the backend
	// know ASAP.
	case request.Preempting:
		return true

	default:
		return false
	}
}
