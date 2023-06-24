package server

import (
	// "flag"
	// "io"
	// "google.golang.org/protobuf/reflect/protoreflect"
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

type FileStream struct {
	wg     *sync.WaitGroup
	inChan chan *service.Record
	path   string

	// FIXME this should be per db
	offset int

	settings   *Settings
	httpClient http.Client
}

func NewFileStream(path string, settings *Settings) *FileStream {
	fs := FileStream{
		wg:       &sync.WaitGroup{},
		path:     path,
		settings: settings,
		inChan:   make(chan *service.Record)}
	fs.wg.Add(1)
	go fs.start()
	return &fs
}

func (fs *FileStream) start() {
	defer fs.wg.Done()

	slog.Debug("FileStream: OPEN")

	if fs.settings.Offline {
		return
	}

	fs.httpClient = newHttpClient(fs.settings.ApiKey)
	for msg := range fs.inChan {
		slog.Debug("FileStream *******")
		LogRecord("FileStream: got record", msg)
		fs.streamRecord(msg)
	}
	slog.Debug("FileStream: finished")
}

func (fs *FileStream) streamRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_History:
		fs.streamHistory(x.History)
	case *service.Record_Exit:
		fs.streamFinish()
	case nil:
		// The field is not set.
		LogFatal("FileStream: RecordType is nil")
	default:
		LogFatal(fmt.Sprintf("FileStream: Unknown type %T", x))
	}
}

func (fs *FileStream) streamHistory(msg *service.HistoryRecord) {

	type FsChunkData struct {
		Offset  int      `json:"offset"`
		Content []string `json:"content"`
	}

	type FsFilesData struct {
		Files map[string]FsChunkData `json:"files"`
	}

	chunk := FsChunkData{
		Offset:  fs.offset,
		Content: []string{jsonify(msg)}}
	fs.offset += 1
	files := map[string]FsChunkData{
		historyFileName: chunk,
	}
	data := FsFilesData{Files: files}
	fs.send(data)
}

func (fs *FileStream) streamFinish() {
	type FsFinishedData struct {
		Complete bool `json:"complete"`
		Exitcode int  `json:"exitcode"`
	}

	data := FsFinishedData{Complete: true, Exitcode: 0}
	fs.send(data)
}

func (fs *FileStream) stream(rec *service.Record) {
	if fs.settings.Offline {
		return
	}
	LogRecord("+++++FileStream: stream", rec)
	fs.inChan <- rec
}

func (fs *FileStream) send(data interface{}) {
	jsonData, err := json.Marshal(data)
	if err != nil {
		LogFatalError("json marshal error", err)
	}

	buffer := bytes.NewBuffer(jsonData)
	req, err := http.NewRequest(http.MethodPost, fs.path, buffer)
	if err != nil {
		LogFatalError("FileStream: could not create request", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := fs.httpClient.Do(req)
	if err != nil {
		LogFatalError("FileStream: error making HTTP request", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {
			LogError("FileStream: error closing response body", err)
		}
	}(resp.Body)

	var res map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		LogError("json decode error", err)
	}
	slog.Debug(fmt.Sprintf("FileStream: post response: %v", res))
}

func jsonify(msg *service.HistoryRecord) string {
	data := make(map[string]interface{})

	for _, item := range msg.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			LogFatal(fmt.Sprintf("json unmarshal error: %v, items: %v", err, item))
		}
		data[item.Key] = val
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		LogError("json marshal error", err)
	}
	return string(jsonData)
}

func (fs *FileStream) close() {
	slog.Debug("FileStream: CLOSE")
	close(fs.inChan)
	fs.wg.Wait()
}
