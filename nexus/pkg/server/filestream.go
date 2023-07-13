package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/service"
)

const (
	HistoryFileName = "wandb-history.jsonl"
	maxItemsPerPush = 5_000
	delayProcess    = 20 * time.Millisecond
	heartbeatTime   = 2 * time.Second
)

var (
	exitcodeZero int  = 0
	completeTrue bool = true
)

type chunkFile int8

const (
	historyChunk chunkFile = iota
	outputChunk
)

type chunkData struct {
	fileData *chunkLine
	Exitcode *int
	Complete *bool
}

type chunkLine struct {
	chunkType chunkFile
	line      string
}

type FileStream struct {
	recordChan chan *service.Record
	recordWait *sync.WaitGroup
	chunkChan  chan chunkData
	chunkWait  *sync.WaitGroup
	replyChan  chan map[string]interface{}
	replyWait  *sync.WaitGroup

	path string

	// FIXME this should be per db
	offset int

	settings   *service.Settings
	logger     *observability.NexusLogger
	httpClient *retryablehttp.Client
}

func NewFileStream(path string, settings *service.Settings, logger *observability.NexusLogger) *FileStream {
	retryClient := newRetryClient(settings.GetApiKey().GetValue(), logger)
	fs := FileStream{
		path:       path,
		settings:   settings,
		logger:     logger,
		httpClient: retryClient,
		recordChan: make(chan *service.Record),
		recordWait: &sync.WaitGroup{},
		chunkChan:  make(chan chunkData),
		chunkWait:  &sync.WaitGroup{},
		replyChan:  make(chan map[string]interface{}),
		replyWait:  &sync.WaitGroup{},
	}
	return &fs
}

func (fs *FileStream) Start() {
	fs.logger.Debug("FileStream: Start")

	fs.recordWait.Add(1)
	go fs.doRecordProcess()
	fs.chunkWait.Add(1)
	go fs.doChunkProcess()
	fs.replyWait.Add(1)
	go fs.doReplyProcess()
}

func (fs *FileStream) pushRecord(rec *service.Record) {
	fs.recordChan <- rec
}

func (fs *FileStream) pushChunk(chunk chunkData) {
	fs.chunkChan <- chunk
}

func (fs *FileStream) pushReply(reply map[string]interface{}) {
	fs.replyChan <- reply
}

func (fs *FileStream) doRecordProcess() {
	defer fs.recordWait.Done()

	fs.logger.Debug("FileStream: OPEN")

	if fs.settings.GetXOffline().GetValue() {
		return
	}

	for msg := range fs.recordChan {
		fs.logger.Debug("FileStream: got record", "record", msg)
		fs.streamRecord(msg)
	}
	fs.logger.Debug("FileStream: finished")
}

func (fs *FileStream) doChunkProcess() {
	defer fs.chunkWait.Done()
	overflow := false

	for active := true; active; {
		var chunkList []chunkData
		select {
		case chunk, ok := <-fs.chunkChan:
			if !ok {
				active = false
				break
			}
			chunkList = append(chunkList, chunk)

			delayTime := delayProcess
			if overflow {
				delayTime = 0
			}
			delayChan := time.After(delayTime)
			overflow = false

			for ready := true; ready; {
				select {
				case chunk, ok := <-fs.chunkChan:
					if !ok {
						ready = false
						active = false
						break
					}
					chunkList = append(chunkList, chunk)
					if len(chunkList) >= maxItemsPerPush {
						ready = false
						overflow = true
					}
				case <-delayChan:
					ready = false
				}
			}
			fs.sendChunkList(chunkList)
		case <-time.After(heartbeatTime):
			fmt.Println("timeout")
			fs.sendChunkList(chunkList)
		}
	}
}

func (fs *FileStream) doReplyProcess() {
	defer fs.replyWait.Done()
	for range fs.replyChan {
	}
}

func (fs *FileStream) streamRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_History:
		fs.streamHistory(x.History)
	case *service.Record_Exit:
		fs.streamFinish()
	case nil:
		// The field is not set.
		err := fmt.Errorf("FileStream: RecordType is nil")
		fs.logger.CaptureFatalAndPanic("FileStream error: field not set", err)
	default:
		err := fmt.Errorf("FileStream: Unknown type %T", x)
		fs.logger.CaptureFatalAndPanic("FileStream error: unknown type", err)
	}
}

func (fs *FileStream) streamHistory(msg *service.HistoryRecord) {
	fs.pushChunk(chunkData{fileData: &chunkLine{chunkType: historyChunk, line: fs.jsonifyHistory(msg)}})
}

func (fs *FileStream) streamFinish() {
	fs.pushChunk(chunkData{Complete: &completeTrue, Exitcode: &exitcodeZero})
}

func (fs *FileStream) StreamRecord(rec *service.Record) {
	if fs.settings.GetXOffline().GetValue() {
		return
	}
	fs.logger.Debug("FileStream: stream", "record", rec)
	fs.pushRecord(rec)
}

/*
 * Data to serialize over filestream
 */
type FsChunkData struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

type FsData struct {
	Files    map[string]FsChunkData `json:"files,omitempty"`
	Complete *bool                  `json:"complete,omitempty"`
	Exitcode *int                   `json:"exitcode,omitempty"`
}

func (fs *FileStream) sendChunkList(chunks []chunkData) {
	var lines []string
	var complete *bool
	var exitcode *int

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

	fsChunk := FsChunkData{
		Offset:  fs.offset,
		Content: lines}
	fs.offset += len(lines)
	chunkFileName := HistoryFileName
	var files map[string]FsChunkData
	if len(lines) > 0 {
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

	buffer := bytes.NewBuffer(jsonData)
	req, err := retryablehttp.NewRequest(http.MethodPost, fs.path, buffer)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("FileStream: could not create request", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := fs.httpClient.Do(req)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("FileStream: error making HTTP request", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {
			fs.logger.CaptureError("FileStream: error closing response body", err)
		}
	}(resp.Body)

	var res map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		fs.logger.CaptureError("json decode error", err)
	}
	fs.pushReply(res)

	fs.logger.Debug(fmt.Sprintf("FileStream: post response: %v", res))
}

func (fs *FileStream) jsonifyHistory(msg *service.HistoryRecord) string {
	data := make(map[string]interface{})

	for _, item := range msg.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			e := fmt.Errorf("json unmarshal error: %v, items: %v", err, item)
			fs.logger.CaptureFatalAndPanic("json unmarshal error", e)
		}
		data[item.Key] = val
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("json unmarshal error", err)
	}
	return string(jsonData)
}

func (fs *FileStream) Close() {
	fs.logger.Debug("FileStream: CLOSE")
	close(fs.recordChan)
	fs.recordWait.Wait()
	close(fs.chunkChan)
	fs.chunkWait.Wait()
	close(fs.replyChan)
	fs.replyWait.Wait()
}
