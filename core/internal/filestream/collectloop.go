package filestream

import (
	"time"

	"golang.org/x/time/rate"
)

// CollectLoop batches changes together to make filestream requests.
//
// This batches all incoming requests while waiting for transmissions
// to go through.
type CollectLoop struct {
	TransmitRateLimit   *rate.Limiter
	MaxRequestSizeBytes int
}

// Start ingests requests and outputs rate-limited, batched requests.
func (cl CollectLoop) Start(
	requests <-chan *FileStreamRequest,
) <-chan *FileStreamRequestReader {
	transmissions := make(chan *FileStreamRequestReader)

	go func() {
		buffer := &FileStreamRequest{}
		isDone := false

		for request := range requests {
			buffer.Merge(request)

			cl.waitForRateLimit(buffer, requests)
			buffer, isDone = cl.transmit(buffer, requests, transmissions)
		}

		for !isDone {
			reader, _ := NewRequestReader(buffer, cl.MaxRequestSizeBytes)
			transmissions <- reader
			buffer, isDone = reader.Next()
		}

		close(transmissions)
	}()

	return transmissions
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
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
	transmissions chan<- *FileStreamRequestReader,
) (*FileStreamRequest, bool) {
	for {
		reader, _ := NewRequestReader(buffer, cl.MaxRequestSizeBytes)

		select {
		case transmissions <- reader:
			return reader.Next()

		case request, ok := <-requests:
			if !ok {
				return buffer, false
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
