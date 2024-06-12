package filestream

import (
	"fmt"
	"io"
	"net/http"
	"sync"

	"github.com/segmentio/encoding/json"
	"github.com/wandb/wandb/core/internal/api"
)

// FsTransmitData is serialized and sent to a W&B server
type FsTransmitData struct {
	Files      map[string]FsTransmitFileData `json:"files,omitempty"`
	Complete   *bool                         `json:"complete,omitempty"`
	Exitcode   *int32                        `json:"exitcode,omitempty"`
	Preempting bool                          `json:"preempting,omitempty"`
	Dropped    int32                         `json:"dropped,omitempty"`
	Uploaded   []string                      `json:"uploaded,omitempty"`
}

// FsServerFileData (part of FsTransmitData) is serialized and sent to a W&B server
type FsTransmitFileData struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

// startProcessingUpdates asynchronously ingests updates.
//
// This returns a channel of actual work to perform to update the filestream's
// next request.
func (fs *fileStream) startProcessingUpdates(
	updates <-chan Update,
) <-chan CollectorStateUpdate {
	stateUpdates := make(chan CollectorStateUpdate)

	go func() {
		defer close(stateUpdates)

		fs.logger.Debug("filestream: open", "path", fs.path)

		for update := range updates {
			err := update.Apply(UpdateContext{
				ModifyRequest: func(csu CollectorStateUpdate) {
					stateUpdates <- csu
				},

				Settings: fs.settings,

				Logger:  fs.logger,
				Printer: fs.printer,
			})

			if err != nil {
				fs.logFatalAndStopWorking(err)
				break
			}
		}

		// Flush input channel if we exited early.
		for range updates {
		}
	}()

	return stateUpdates
}

// startTransmitting makes requests to the filestream API.
//
// It ingests a channel of updates and outputs a channel of API responses.
//
// Updates are batched to reduce the total number of HTTP requests.
// An empty "heartbeat" request is sent when there are no updates for too long,
// guaranteeing that a request is sent at least once every period specified
// by `heartbeatStopwatch`.
func (fs *fileStream) startTransmitting(
	stateUpdates <-chan CollectorStateUpdate,
	initialOffsets FileStreamOffsetMap,
) <-chan map[string]any {
	// Output channel of responses.
	feedback := make(chan map[string]any)

	// Internal channel of actual requests to make.
	transmissions := make(chan *FsTransmitData)

	transmitWG := &sync.WaitGroup{}
	transmitWG.Add(1)
	go func() {
		defer func() {
			close(feedback)
			transmitWG.Done()
		}()

		fs.sendAll(transmissions, feedback)
	}()

	// Periodically send heartbeats.
	//
	// We do this by pushing a transmission if no requests are sent for too
	// long---that is, when the heartbeat stopwatch hits zero. Whenever we
	// transmit, we reset the stopwatch.
	stopHearbeat := make(chan struct{})
	heartbeatWG := &sync.WaitGroup{}
	heartbeatWG.Add(1)
	go func() {
		defer heartbeatWG.Done()
		fs.sendHeartbeats(stopHearbeat, transmissions)
	}()

	go func() {
		state := NewCollectorState(initialOffsets)

		// Batch and send updates.
		//
		// We try to batch updates that happen in quick succession by waiting a
		// short time after receiving an update.
		for firstUpdate := range stateUpdates {
			firstUpdate.Apply(&state)
			fs.collectBatch(&state, stateUpdates)

			fs.heartbeatStopwatch.Reset()
			data, hasData := state.MakeRequest(false /*isDone*/)
			if hasData {
				transmissions <- data
			}
		}

		// Stop sending heartbeats.
		close(stopHearbeat)
		heartbeatWG.Wait()

		// Send final transmission.
		data, _ := state.MakeRequest(true /*isDone*/)
		transmissions <- data
		close(transmissions)
		transmitWG.Wait()
	}()

	return feedback
}

// startProcessingFeedback processes feedback from the filestream API.
//
// This increments the wait group and decrements it after completing
// all work.
func (fs *fileStream) startProcessingFeedback(
	feedback <-chan map[string]any,
	wg *sync.WaitGroup,
) {
	wg.Add(1)
	go func() {
		defer wg.Done()

		for range feedback {
		}
	}()
}

func (fs *fileStream) sendHeartbeats(
	stop <-chan struct{},
	out chan<- *FsTransmitData,
) {
	for keepGoing := true; keepGoing; {
		select {
		case <-fs.heartbeatStopwatch.Wait():
			fs.heartbeatStopwatch.Reset()
			out <- &FsTransmitData{}
		case <-stop:
			keepGoing = false
		}
	}
}

func (fs *fileStream) collectBatch(
	state *CollectorState,
	updates <-chan CollectorStateUpdate,
) {
	maxChunkWait := fs.delayProcess.Wait()

	for keepGoing := true; keepGoing; {
		select {
		case update, ok := <-updates:
			if ok {
				update.Apply(state)
			} else {
				keepGoing = false
			}
		case <-maxChunkWait:
			keepGoing = false
		}
	}
}

func (fs *fileStream) sendAll(
	data <-chan *FsTransmitData,
	feedbackChan chan<- map[string]any,
) {
	for x := range data {
		err := fs.send(*x, feedbackChan)

		if err != nil {
			fs.logFatalAndStopWorking(err)
			break
		}
	}

	// Flush the channel, in case the loop above ended with an error.
	for range data {
	}
}

func (fs *fileStream) send(
	data FsTransmitData,
	feedbackChan chan<- map[string]any,
) error {
	// Stop working after death to avoid data corruption.
	if fs.isDead() {
		return fmt.Errorf("filestream: can't send because I am dead")
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("filestream: json marshall error in send(): %v", err)
	}
	fs.logger.Debug("filestream: post request", "request", string(jsonData))

	req := &api.Request{
		Method: http.MethodPost,
		Path:   fs.path,
		Body:   jsonData,
		Headers: map[string]string{
			"Content-Type": "application/json",
		},
	}

	resp, err := fs.apiClient.Send(req)

	switch {
	case err != nil:
		return fmt.Errorf(
			"filestream: error making HTTP request: %v. got response: %v",
			err,
			resp,
		)
	case resp == nil:
		// Sometimes resp and err can both be nil in retryablehttp's Client.
		return fmt.Errorf("filestream: nil response and nil error for request to %v", req.Path)
	case resp.StatusCode < 200 || resp.StatusCode > 300:
		// If we reach here, that means all retries were exhausted. This could
		// mean, for instance, that the user's internet connection broke.
		return fmt.Errorf("filestream: failed to upload: %v", resp.Status)
	}

	defer func(Body io.ReadCloser) {
		if err = Body.Close(); err != nil {
			fs.logger.CaptureError("filestream: error closing response body", err)
		}
	}(resp.Body)

	var res map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		fs.logger.CaptureError("json decode error", err)
	}
	feedbackChan <- res
	fs.logger.Debug("filestream: post response", "response", res)
	return nil
}
