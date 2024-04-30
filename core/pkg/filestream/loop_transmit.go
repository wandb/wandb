package filestream

import (
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
		heartbeatDelay:  fs.pollInterval,
		processDelay:    fs.delayProcess,
		maxItemsPerPush: fs.maxItemsPerPush,
	}
	for !collector.isDone {
		data, ok := collector.CollectAndDump(fs.offsetMap)

		if ok {
			fs.send(data)
			fs.heartbeatStopwatch.Reset()
		} else if fs.heartbeatStopwatch.IsDone() {
			fs.send(&FsTransmitData{})
			fs.heartbeatStopwatch.Reset()
		}
	}
}

func (fs *fileStream) send(data *FsTransmitData) {
	jsonData, err := json.Marshal(data)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("filestream: json marshal error", err)
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
	if err != nil {
		fs.logger.CaptureFatalAndPanic("filestream: error making HTTP request", err)
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
}
