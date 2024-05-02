package filestream

import (
	"fmt"
	"io"
	"net/http"

	"github.com/segmentio/encoding/json"
	"github.com/wandb/wandb/core/internal/api"
)

// FsTransmitData is serialized and sent to a W&B server
type FsTransmitData struct {
	Files      map[string]fsTransmitFileData `json:"files,omitempty"`
	Complete   *bool                         `json:"complete,omitempty"`
	Exitcode   *int32                        `json:"exitcode,omitempty"`
	Preempting bool                          `json:"preempting,omitempty"`
	Dropped    int32                         `json:"dropped,omitempty"`
	Uploaded   []string                      `json:"uploaded,omitempty"`
}

// FsServerFileData (part of FsTransmitData) is serialized and sent to a W&B server
type fsTransmitFileData struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

func (fs *fileStream) addTransmit(chunk processedChunk) {
	fs.transmitChan <- chunk
}

func (fs *fileStream) loopTransmit(inChan <-chan processedChunk) {
	collector := chunkCollector{
		input:           inChan,
		processDelay:    fs.delayProcess,
		maxItemsPerPush: fs.maxItemsPerPush,
	}
	for !collector.isDone {
		data, ok := collector.CollectAndDump(fs.offsetMap)

		if ok {
			if err := fs.send(data); err != nil {
				fs.logFatalAndStopWorking(err)
				return
			}

			fs.heartbeatStopwatch.Reset()
		} else if fs.heartbeatStopwatch.IsDone() {
			if err := fs.send(&FsTransmitData{}); err != nil {
				fs.logFatalAndStopWorking(err)
				return
			}

			fs.heartbeatStopwatch.Reset()
		}
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

	// TODO: Process response.

	fs.logger.Debug("filestream: post response", "response", res)
	return nil
}
