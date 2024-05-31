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

// loopProcess ingests the processChan to process incoming data into
// FS requests.
func (fs *fileStream) loopProcess() {
	// Close the output channel at the end.
	defer close(fs.transmitChan)

	fs.logger.Debug("filestream: open", "path", fs.path)

	for update := range fs.processChan {
		err := update.Apply(UpdateContext{
			ModifyRequest: func(csu CollectorStateUpdate) {
				fs.transmitChan <- csu
			},

			Settings: fs.settings,
			ClientID: fs.clientId,

			Logger:  fs.logger,
			Printer: fs.printer,
		})

		if err != nil {
			fs.logFatalAndStopWorking(err)
			break
		}
	}

	// Flush input channel if we exited early.
	for range fs.processChan {
	}
}

// loopTransmit sends updates in the transmitChan to the backend.
//
// Updates are batched to reduce the total number of HTTP requests.
// An empty "heartbeat" request is sent when there are no updates for too long,
// guaranteeing that a request is sent at least once every period specified
// by `heartbeatStopwatch`.
func (fs *fileStream) loopTransmit() {
	// Close the output channel at the end.
	defer close(fs.feedbackChan)

	state := CollectorState{}

	transmissions := make(chan *FsTransmitData)

	transmitWG := &sync.WaitGroup{}
	transmitWG.Add(1)
	go func() {
		defer transmitWG.Done()
		fs.sendAll(transmissions, fs.feedbackChan)
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

	// Batch and send updates.
	//
	// We try to batch updates that happen in quick succession by waiting a
	// short time after receiving an update.
	for firstUpdate := range fs.transmitChan {
		firstUpdate.Apply(&state)
		fs.collectBatch(&state, fs.transmitChan)

		fs.heartbeatStopwatch.Reset()
		data, hasData := state.Consume(fs.offsetMap, false /*isDone*/)
		if hasData {
			transmissions <- data
		}
	}

	// Stop sending heartbeats.
	close(stopHearbeat)
	heartbeatWG.Wait()

	// Send final transmission.
	data, _ := state.Consume(fs.offsetMap, true /*isDone*/)
	transmissions <- data
	close(transmissions)
	transmitWG.Wait()
}

// loopFeedback consumes the feedbackChan to process feedback from the backend.
func (fs *fileStream) loopFeedback() {
	for range fs.feedbackChan {
	}
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
		return fmt.Errorf("filestream: error making HTTP request: %v", err)
	case resp == nil:
		// Sometimes resp and err can both be nil in retryablehttp's Client.
		return fmt.Errorf("filestream: nil response and nil error")
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
