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
	// Send data as it comes in.
	case x, ok := <-data:
		if !ok {
			return nil, false
		}
		return x.GetJSON(state), true

	// If data doesn't come in time, send a heartbeat.
	case <-heartbeat.Wait():
		return &FileStreamRequestJSON{}, true
	}
}
