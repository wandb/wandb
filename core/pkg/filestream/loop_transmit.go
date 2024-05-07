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

func (fs *fileStream) addTransmit(chunk CollectorStateUpdate) {
	fs.transmitChan <- chunk
}

func (fs *fileStream) loopTransmit(updates <-chan CollectorStateUpdate) {
	state := CollectorState{}

	transmissions := make(chan *FsTransmitData)

	transmitWG := &sync.WaitGroup{}
	transmitWG.Add(1)
	go func() {
		defer transmitWG.Done()
		fs.sendAll(transmissions)
	}()

	// Periodically send heartbeats.
	stopHearbeat := make(chan struct{})
	heartbeatWG := &sync.WaitGroup{}
	heartbeatWG.Add(1)
	go func() {
		defer heartbeatWG.Done()
		fs.sendHeartbeats(stopHearbeat, transmissions)
	}()

	// Batch and send updates.
	for firstUpdate := range updates {
		firstUpdate.Apply(&state)
		fs.collectBatch(&state, updates)

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

func (fs *fileStream) sendAll(data <-chan *FsTransmitData) {
	for x := range data {
		err := fs.send(x)

		if err != nil {
			fs.logFatalAndStopWorking(err)
			break
		}
	}

	// Flush the channel, in case the loop above ended with an error.
	for range data {
	}
}

func (fs *fileStream) send(data *FsTransmitData) error {
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
	fs.addFeedback(res)
	fs.logger.Debug("filestream: post response", "response", res)
	return nil
}
