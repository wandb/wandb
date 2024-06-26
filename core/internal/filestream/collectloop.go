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
	stateUpdates <-chan CollectorStateUpdate,
	initialOffsets FileStreamOffsetMap,
) <-chan *FsTransmitData {
	transmissions := make(chan *FsTransmitData)

	go func() {
		state := NewCollectorState(initialOffsets)

		for update := range stateUpdates {
			update.Apply(&state)

			cl.waitForRateLimit(&state, stateUpdates)
			cl.transmit(&state, stateUpdates, transmissions)
		}

		// Send final transmission.
		transmissions <- state.PrepRequest(true)
		state.RequestSent()
		close(transmissions)
	}()

	return transmissions
}

// waitForRateLimit applies updates until the rate limit allows us
// to make a request.
func (cl CollectLoop) waitForRateLimit(
	state *CollectorState,
	updates <-chan CollectorStateUpdate,
) {
	if shouldSendASAP(state) {
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

		case update, ok := <-updates:
			_ = timer.Stop()

			if !ok {
				return
			}

			update.Apply(state)

			if shouldSendASAP(state) {
				return
			}
		}
	}
}

// transmit applies updates until a request goes through.
func (cl CollectLoop) transmit(
	state *CollectorState,
	updates <-chan CollectorStateUpdate,
	transmissions chan<- *FsTransmitData,
) {
batchingLoop:
	for {
		select {
		case transmissions <- state.PrepRequest(false /*isDone*/):
			state.RequestSent()
			break batchingLoop

		case update, ok := <-updates:
			if !ok {
				break batchingLoop
			}

			update.Apply(state)
		}
	}
}

// shouldSendASAP returns a request should be made regardless of rate limits.
func shouldSendASAP(state *CollectorState) bool {
	// Send the "pre-empting" state immediately.
	//
	// This state indicates that the process may be about to yield the
	// CPU for an unknown amount of time, and we want to let the backend
	// know ASAP.
	return state.HasPreempting
}
