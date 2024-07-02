package filestream

import (
	"github.com/wandb/wandb/core/internal/waiting"
)

// TransmitLoop makes requests to the backend.
type TransmitLoop struct {
	HeartbeatStopwatch     waiting.Stopwatch
	Send                   func(*FileStreamRequestJSON, chan<- map[string]any) error
	LogFatalAndStopWorking func(error)
}

// Start makes requests to the filestream API.
//
// It ingests a channel of requests and outputs a channel of API responses.
func (tr TransmitLoop) Start(
	data <-chan *FileStreamRequestReader,
	offsets FileStreamOffsetMap,
) <-chan map[string]any {
	feedback := make(chan map[string]any)

	go func() {
		defer func() {
			// Flush the input channel.
			for range data {
			}

			// Close the output channel.
			close(feedback)
		}()

		state := &FileStreamState{}
		if offsets != nil {
			state.HistoryLineNum = offsets[HistoryChunk]
			state.EventsLineNum = offsets[EventsChunk]
			state.SummaryLineNum = offsets[SummaryChunk]
			state.ConsoleLineOffset = offsets[OutputChunk]
		}

		for {
			x, ok := readWithHeartbeat(state, data, tr.HeartbeatStopwatch)
			if !ok {
				break
			}

			tr.HeartbeatStopwatch.Reset()
			err := tr.Send(x, feedback)

			if err != nil {
				tr.LogFatalAndStopWorking(err)
				break
			}
		}
	}()

	return feedback
}

// readWithHeartbeat waits for data or a heartbeat.
//
// A heartbeat is an empty request that is sent if no data is sent
// for too long. It indicates to the server that we're still alive.
func readWithHeartbeat(
	state *FileStreamState,
	data <-chan *FileStreamRequestReader,
	heartbeat waiting.Stopwatch,
) (*FileStreamRequestJSON, bool) {
	select {
	// If data is available now, send it.
	case x, ok := <-data:
		if !ok {
			return nil, false
		}
		return x.GetJSON(state), true

	// Otherwise, wait for data to arrive or a heartbeat to happen.
	//
	// We need this in a separate 'default' case because Go selects a random
	// available case, so if data is available and the stopwatch is finished,
	// Go might send a heartbeat instead of the data. This could be a problem
	// on slow internet connections with a long roundtrip time.
	default:
		select {
		case x, ok := <-data:
			if !ok {
				return nil, false
			}
			return x.GetJSON(state), true

		case <-heartbeat.Wait():
			return &FileStreamRequestJSON{}, true
		}
	}
}
