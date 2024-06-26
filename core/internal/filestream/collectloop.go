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
	TransmitRateLimit *rate.Limiter
}

// Start ingests updates and outputs rate-limited requests.
func (cl CollectLoop) Start(
	mutations <-chan BufferMutation,
	initialOffsets FileStreamOffsetMap,
) <-chan *FileStreamRequest {
	transmissions := make(chan *FileStreamRequest)

	go func() {
		buffer := &FileStreamRequestBuffer{}
		if initialOffsets != nil {
			buffer.HistoryLineNum = initialOffsets[HistoryChunk]
			buffer.EventsLineNum = initialOffsets[EventsChunk]
			buffer.SummaryLineNum = initialOffsets[SummaryChunk]
			buffer.ConsoleLogLineOffset = initialOffsets[OutputChunk]
		}

		for mutate := range mutations {
			mutate(buffer)

			cl.waitForRateLimit(buffer, mutations)
			buffer = cl.transmit(buffer, mutations, transmissions)
		}

		// Send all remaining data, which may require multiple requests.
		buffer.Finalize()
		for {
			request, isFinal, advancer := buffer.Get()
			buffer = advancer.Advance()
			transmissions <- request

			if isFinal {
				break
			}
		}

		close(transmissions)
	}()

	return transmissions
}

// waitForRateLimit applies updates until the rate limit allows us
// to make a request.
func (cl CollectLoop) waitForRateLimit(
	buffer *FileStreamRequestBuffer,
	mutations <-chan BufferMutation,
) {
	if shouldSendASAP(buffer) {
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

		case mutate, ok := <-mutations:
			_ = timer.Stop()

			if !ok {
				return
			}

			mutate(buffer)

			if shouldSendASAP(buffer) {
				return
			}
		}
	}
}

// transmit applies updates until a request goes through.
func (cl CollectLoop) transmit(
	buffer *FileStreamRequestBuffer,
	mutations <-chan BufferMutation,
	transmissions chan<- *FileStreamRequest,
) *FileStreamRequestBuffer {
	for {
		request, _, advancer := buffer.Get()

		select {
		case transmissions <- request:
			return advancer.Advance()

		case mutate, ok := <-mutations:
			if !ok {
				return buffer
			}

			mutate(buffer)
		}
	}
}

// shouldSendASAP returns a request should be made regardless of rate limits.
func shouldSendASAP(buffer *FileStreamRequestBuffer) bool {
	// Send the "pre-empting" state immediately.
	//
	// This state indicates that the process may be about to yield the
	// CPU for an unknown amount of time, and we want to let the backend
	// know ASAP.
	return buffer.Preempting != nil
}
