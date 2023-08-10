package filestream

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/hashicorp/go-retryablehttp"
)

var completeTrue bool = true

type chunkData struct {
	fileName string
	fileData *chunkLine
	Exitcode *int32
	Complete *bool
}

type chunkLine struct {
	chunkType ChunkFile
	line      string
}

// FsChunkData is the data for a chunk of a file
type FsChunkData struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

type FsData struct {
	Files    map[string]FsChunkData `json:"files,omitempty"`
	Complete *bool                  `json:"complete,omitempty"`
	Exitcode *int32                 `json:"exitcode,omitempty"`
}

func (fs *FileStream) addTransmit(chunk chunkData) {
	fs.transmitChan <- chunk
}

func (fs *FileStream) loopTransmit(inChan <-chan chunkData) {

	overflow := false

	for active := true; active; {
		var chunkMaps = make(map[string][]chunkData)
		select {
		case chunk, ok := <-inChan:
			if !ok {
				active = false
				break
			}

			chunkMaps[chunk.fileName] = append(chunkMaps[chunk.fileName], chunk)

			delayTime := fs.delayProcess
			if overflow {
				delayTime = 0
			}
			delayChan := time.After(delayTime)
			overflow = false

			for ready := true; ready; {
				select {
				case chunk, ok = <-inChan:
					if !ok {
						ready = false
						active = false
						break
					}
					chunkMaps[chunk.fileName] = append(chunkMaps[chunk.fileName], chunk)
					if len(chunkMaps[chunk.fileName]) >= fs.maxItemsPerPush {
						ready = false
						overflow = true
					}
				case <-delayChan:
					ready = false
				}
			}
			for _, chunkList := range chunkMaps {
				fs.sendChunkList(chunkList)
			}
		case <-time.After(fs.heartbeatTime):
			for _, chunkList := range chunkMaps {
				if len(chunkList) > 0 {
					fs.sendChunkList(chunkList)
				}
			}
		}
		if fs.stageExitChunk != nil {
			fs.sendChunkList([]chunkData{*fs.stageExitChunk})
		}
	}
}

func (fs *FileStream) sendChunkList(chunks []chunkData) {
	var lines []string
	var complete *bool
	var exitcode *int32

	for i := range chunks {
		if chunks[i].fileData != nil {
			lines = append(lines, chunks[i].fileData.line)
		}
		if chunks[i].Complete != nil {
			complete = chunks[i].Complete
		}
		if chunks[i].Exitcode != nil {
			exitcode = chunks[i].Exitcode
		}
	}
	var files map[string]FsChunkData
	if len(lines) > 0 {
		// all chunks in the list should have the same file name
		chunkType := chunks[0].fileData.chunkType
		chunkFileName := chunks[0].fileName
		fsChunk := FsChunkData{
			Offset:  fs.offsetMap[chunkType],
			Content: lines}
		fs.offsetMap[chunkType] += len(lines)
		files = map[string]FsChunkData{
			chunkFileName: fsChunk,
		}
	}
	data := FsData{Files: files, Complete: complete, Exitcode: exitcode}
	fs.send(data)
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
