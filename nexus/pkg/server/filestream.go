package server

import (
	// "flag"
	// "io"
	// "google.golang.org/protobuf/reflect/protoreflect"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"

	log "github.com/sirupsen/logrus"
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

	log.Debug("FileStream: OPEN")

	if fs.settings.Offline {
		return
	}

	fs.httpClient = newHttpClient(fs.settings.ApiKey)
	for msg := range fs.inChan {
		log.Debug("FileStream *******")
		log.WithFields(log.Fields{"record": msg}).Debug("FileStream: got record")
		fs.streamRecord(msg)
	}
	log.Debug("FileStream: finished")
}

func (fs *FileStream) streamRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_History:
		fs.streamHistory(x.History)
	case *service.Record_Exit:
		fs.streamFinish()
	case nil:
		// The field is not set.
		log.Fatal("FileStream: RecordType is nil")
	default:
		log.Fatalf("FileStream: Unknown type %T", x)
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
	log.Debug("+++++FileStream: stream", rec)
	fs.inChan <- rec
}

func (fs *FileStream) send(data interface{}) {
	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Fatalf("json marshal error: %v", err)
	}

	buffer := bytes.NewBuffer(jsonData)
	req, err := http.NewRequest(http.MethodPost, fs.path, buffer)
	if err != nil {
		log.Fatalf("FileStream: could not create request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := fs.httpClient.Do(req)
	if err != nil {
		log.Fatalf("FileStream: error making HTTP request: %v", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {
			log.Errorf("FileStream: error closing response body: %v", err)
		}
	}(resp.Body)

	var res map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&res)
	if err != nil {
		log.Errorf("json decode error: %v", err)
	}
	log.WithFields(log.Fields{"res": res}).Debug("FileStream: post response")
}

func jsonify(msg *service.HistoryRecord) string {
	data := make(map[string]interface{})

	for _, item := range msg.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			log.Fatalf("json unmarshal error: %v, items: %v", err, item)
		}
		data[item.Key] = val
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Errorf("json marshal error: %v", err)
	}
	return string(jsonData)
}

func (fs *FileStream) close() {
	log.Debug("FileStream: CLOSE")
	close(fs.inChan)
	fs.wg.Wait()
}
