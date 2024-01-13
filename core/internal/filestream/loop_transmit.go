package filestream

import (
	"bytes"
	"io"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/segmentio/encoding/json"
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

func (fs *FileStream) addTransmit(chunk processedChunk) {
	fs.transmitChan <- chunk
}

func (fs *FileStream) loopTransmit(inChan <-chan processedChunk) {
	collector := chunkCollector{
		input:           inChan,
		heartbeatTime:   fs.heartbeatTime,
		delayProcess:    fs.delayProcess,
		maxItemsPerPush: fs.maxItemsPerPush,
	}
	for !collector.isDone {
		if readMore := collector.read(); readMore {
			collector.readMore()
		}
		data := collector.dump(fs.offsetMap)
		if data != nil {
			fs.send(data)
		}
	}
}

func (fs *FileStream) send(data interface{}) {
	jsonData, err := json.Marshal(data)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("json marshal error", err)
	}
	fs.logger.Debug("filestream: post request", "request", string(jsonData))

	buffer := bytes.NewBuffer(jsonData)
	req, err := retryablehttp.NewRequest(http.MethodPost, fs.path, buffer)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("filestream: error creating HTTP request", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := fs.httpClient.Do(req)
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
