package filestream

import "time"

// TransmitLoop makes requests to the backend.
type TransmitLoop struct {
	HeartbeatPeriod        time.Duration
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

		heartbeat := time.NewTicker(tr.HeartbeatPeriod)

		for {
			x, ok := data.NextRequest(heartbeat.C)
			if !ok {
				break
			}

			heartbeat.Reset(tr.HeartbeatPeriod)
			err := tr.Send(x, feedback)

			if err != nil {
				tr.LogFatalAndStopWorking(err)
				break
			}
		}
	}()

	return feedback
}
