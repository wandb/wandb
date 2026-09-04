package filestream

import (
	"time"

	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/observability"
)

// CollectLoop batches changes together to make filestream requests.
//
// This batches all incoming requests while waiting for transmissions
// to go through.
type CollectLoop struct {
	Logger  *observability.CoreLogger
	Printer *observability.Printer

	// TransmitInterval is the steady-state time between transmissions.
	TransmitInterval time.Duration

	// InitialTransmitInterval is the time between transmissions once the
	// run's first history is collected. It doubles after each rate-limited
	// transmission until it reaches TransmitInterval, so that a run's first
	// logged data reaches the backend quickly.
	//
	// There is no ramp if it is not positive or not less than
	// TransmitInterval.
	InitialTransmitInterval time.Duration

	// transmitRateLimit allows one transmission per transmitInterval.
	transmitRateLimit *rate.Limiter

	// transmitInterval is the current time between transmissions.
	transmitInterval time.Duration

	// transmitRampStarted is whether the run's first history was collected.
	transmitRampStarted bool
}

// Start ingests requests and outputs rate-limited, batched requests.
func (cl *CollectLoop) Start(
	state *FileStreamState,
	requests <-chan *FileStreamRequest,
) *TransmitChan {
	switch {
	case cl.Logger == nil:
		panic("filestream: CollectLoop.Logger is nil")
	case cl.Printer == nil:
		panic("filestream: CollectLoop.Printer is nil")
	}

	cl.transmitInterval = cl.TransmitInterval
	cl.transmitRateLimit = rate.NewLimiter(rate.Every(cl.transmitInterval), 1)

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
			json, hasMore = cl.pop(state, buffer)
			output.Push(json)
		}

		output.Close()
	}()

	return output
}

// waitForRateLimit merges requests until the rate limit allows us
// to transmit data.
func (cl *CollectLoop) waitForRateLimit(
	state *FileStreamState,
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
) {
	cl.maybeStartTransmitRamp(buffer)

	if cl.shouldSendASAP(state, buffer) {
		return
	}

	reservation := cl.transmitRateLimit.Reserve()
	isDelayed := reservation.Delay() > 0

	for {
		timer := time.NewTimer(reservation.Delay())
		select {
		case <-timer.C:
			// Each rate-limited transmission during the ramp doubles the
			// interval for the next one.
			if isDelayed && cl.transmitInterval < cl.TransmitInterval {
				cl.transmitInterval =
					min(2*cl.transmitInterval, cl.TransmitInterval)
				cl.transmitRateLimit.SetLimit(rate.Every(cl.transmitInterval))
			}
			return

		case request, ok := <-requests:
			_ = timer.Stop()

			if !ok {
				return
			}

			buffer.Merge(request)
			startedRamp := cl.maybeStartTransmitRamp(request)

			if cl.shouldSendASAP(state, buffer) {
				return
			}

			// Apply the sped-up rate limit to this batch unless it is
			// already due: cancelling an overdue reservation is a no-op,
			// so re-reserving would charge a second token.
			if startedRamp {
				now := time.Now()
				if reservation.DelayFrom(now) > 0 {
					reservation.CancelAt(now)
					reservation = cl.transmitRateLimit.ReserveN(now, 1)
				}
			}
		}
	}
}

// maybeStartTransmitRamp speeds up transmissions if the request contains
// the run's first history, returning whether the rate limit changed.
func (cl *CollectLoop) maybeStartTransmitRamp(request *FileStreamRequest) bool {
	if cl.transmitRampStarted || len(request.HistoryLines) == 0 {
		return false
	}
	cl.transmitRampStarted = true

	initial := cl.InitialTransmitInterval
	if initial <= 0 || initial >= cl.TransmitInterval {
		return false
	}

	cl.transmitInterval = initial
	cl.transmitRateLimit.SetLimit(rate.Every(initial))
	return true
}

// transmit accumulates incoming requests until a transmission goes through.
//
// Returns whether there remains unsent data in the buffer.
func (cl *CollectLoop) transmit(
	state *FileStreamState,
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
	output *TransmitChan,
) bool {
	for {
		// If we're at max size, stop adding to the buffer.
		if state.IsAtSizeLimit(buffer) {
			cl.Logger.Info("filestream: waiting to send request of max size")
			json, hasMore := cl.pop(state, buffer)
			output.Push(json)
			return hasMore
		}

		// Otherwise, either send the buffer or add to it.
		select {
		case pushChan := <-output.PreparePush():
			json, hasMore := cl.pop(state, buffer)
			pushChan <- json
			return hasMore

		case request, ok := <-requests:
			if !ok {
				json, hasMore := cl.pop(state, buffer)
				output.Push(json)
				return hasMore
			}

			buffer.Merge(request)
			cl.maybeStartTransmitRamp(request)
		}
	}
}

// pop calls [FileStreamState.Pop], extracting a JSON value to send from the
// request and returning whether the request contains more data.
func (cl *CollectLoop) pop(
	state *FileStreamState,
	request *FileStreamRequest,
) (*FileStreamRequestJSON, bool) {
	return state.Pop(
		request,
		cl.Logger,
		cl.Printer,
	)
}

// shouldSendASAP returns a request should be made regardless of rate limits.
func (cl *CollectLoop) shouldSendASAP(
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
	case state.IsAtSizeLimit(request):
		return true

	default:
		return false
	}
}
