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
	data *TransmitChan,
) <-chan map[string]any {
	feedback := make(chan map[string]any)

	go func() {
		defer func() {
			data.IgnoreFutureRequests()
			close(feedback)
		}()

		for {
			x, ok := data.NextRequest(tr.HeartbeatStopwatch)
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
