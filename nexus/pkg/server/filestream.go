package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"

	"golang.org/x/exp/slog"
)

const historyFileName = "wandb-history.jsonl"

type FsChunkData struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

type FsFilesData struct {
	Files map[string]FsChunkData `json:"files"`
}

type FsFinishedData struct {
	Complete bool `json:"complete"`
	Exitcode int  `json:"exitcode"`
}

type FileStream struct {
	wg     *sync.WaitGroup
	inChan chan *service.Record
	path   string

	// FIXME this should be per db
	offset int

	settings   *service.Settings
	logger     *slog.Logger
	httpClient http.Client
}

func NewFileStream(path string, settings *service.Settings, logger *slog.Logger) *FileStream {
	fs := FileStream{
		wg:       &sync.WaitGroup{},
		path:     path,
		settings: settings,
		logger:   logger,
		inChan:   make(chan *service.Record)}
	fs.wg.Add(1)
	go fs.do()
	return &fs
}

func (fs *FileStream) do() {
	defer fs.wg.Done()

	fs.logger.Debug("FileStream: do")

	if fs.settings.GetXOffline().GetValue() {
		return
	}

	fs.httpClient = newHttpClient(fs.settings.GetApiKey().GetValue())
	for msg := range fs.inChan {
		LogRecord(fs.logger, "FileStream: got record", msg)
		fs.streamRecord(msg)
	}
	fs.logger.Debug("FileStream: finished")
}

func (fs *FileStream) streamRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_History:
		fs.streamHistory(x.History)
	case *service.Record_Exit:
		fs.streamFinish()
	case nil:
		// The field is not set.
		LogFatal(fs.logger, "FileStream: RecordType is nil")
	default:
		LogFatal(fs.logger, fmt.Sprintf("FileStream: Unknown type %T", x))
	}
}

func (fs *FileStream) streamHistory(msg *service.HistoryRecord) {
	chunk := FsChunkData{
		Offset:  fs.offset,
		Content: []string{jsonify(msg, fs.logger)}}
	fs.offset += 1
	files := map[string]FsChunkData{
		historyFileName: chunk,
	}
	data := FsFilesData{Files: files}
	fs.send(data)
}

func (fs *FileStream) streamFinish() {
	data := FsFinishedData{Complete: true, Exitcode: 0}
	fs.send(data)
}

func (fs *FileStream) stream(rec *service.Record) {
	if fs.settings.GetXOffline().GetValue() {
		return
	}
	LogRecord(fs.logger, "+++++FileStream: stream", rec)
	fs.inChan <- rec
}

func (fs *FileStream) send(data interface{}) {
	jsonData, err := json.Marshal(data)
	if err != nil {
		LogFatalError(fs.logger, "json marshal error", err)
	}

	buffer := bytes.NewBuffer(jsonData)
	req, err := http.NewRequest(http.MethodPost, fs.path, buffer)
	if err != nil {
		LogFatalError(fs.logger, "FileStream: could not create request", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := fs.httpClient.Do(req)
	if err != nil {
		LogFatalError(fs.logger, "FileStream: error making HTTP request", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {
			LogError(fs.logger, "FileStream: error closing response body", err)
		}
	}(resp.Body)

	var res map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		LogError(fs.logger, "json decode error", err)
	}
	fs.logger.Debug(fmt.Sprintf("FileStream: post response: %v", res))
}

func jsonify(msg *service.HistoryRecord, logger *slog.Logger) string {
	data := make(map[string]interface{})

	for _, item := range msg.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			LogFatal(logger, fmt.Sprintf("json unmarshal error: %v, items: %v", err, item))
		}
		data[item.Key] = val
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		LogError(logger, "json marshal error", err)
	}
	return string(jsonData)
}

func (fs *FileStream) close() {
	fs.logger.Debug("FileStream: CLOSE")
	close(fs.inChan)
	fs.wg.Wait()
}
