package server

import (
	// "flag"
	// "io"
	// "google.golang.org/protobuf/reflect/protoreflect"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"

	"github.com/wandb/wandb/nexus/service"
	"sync"

	log "github.com/sirupsen/logrus"
)

type FileStream struct {
	wg          *sync.WaitGroup
	fstreamChan chan service.Record
	fstreamPath string

	// FIXME this should be per file
	offset int

	settings   *Settings
	httpClient http.Client
}

func NewFileStream(wg *sync.WaitGroup, fstreamPath string, settings *Settings) *FileStream {
	fs := FileStream{
		wg:          wg,
		fstreamPath: fstreamPath,
		settings:    settings,
		fstreamChan: make(chan service.Record)}
	wg.Add(1)
	go fs.fstreamGo()
	return &fs
}

func (fs *FileStream) Stop() {
	// Must be called from handler
	close(fs.fstreamChan)
}

func (fs *FileStream) StreamRecord(rec *service.Record) {
	if fs.settings.Offline {
		return
	}
	fs.fstreamChan <-*rec
}

func (fs *FileStream) fstreamInit() {
	httpClient := http.Client{
		Transport: &authedTransport{
			key:     fs.settings.ApiKey,
			wrapped: http.DefaultTransport,
		},
	}
	fs.httpClient = httpClient
}

func (fs *FileStream) send(fsdata interface{}) {
	json_data, err := json.Marshal(fsdata)
	// fmt.Println("ABOUT TO", string(json_data))

	buffer := bytes.NewBuffer(json_data)
	req, err := http.NewRequest(http.MethodPost, fs.fstreamPath, buffer)
	if err != nil {
		fmt.Printf("client: could not create request: %s\n", err)
		os.Exit(1)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := fs.httpClient.Do(req)
	if err != nil {
		fmt.Printf("client: error making http request: %s\n", err)
		os.Exit(1)
	}

	var res map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&res)
	log.WithFields(log.Fields{"res": res}).Debug("FSTREAM: post response")
}

/*
    "complete": False,
    "failed": False,
    "dropped": self._dropped_chunks,
    "uploaded": list(uploaded),

    "complete": False,
    "preempting": True,
    "dropped": self._dropped_chunks,
    "uploaded": list(uploaded),

	fs={"fname": {"content": ["fdsf", "fdfs"], offset=}}
	or
    return {"offset": self._offset, "content": enc, "encoding": "base64"}
    json={"files": fs, "dropped": self._dropped_chunks},

    "complete": True,
    "exitcode": int(finished.exitcode),
    "dropped": self._dropped_chunks,
    "uploaded": list(uploaded),
 */

func (fs *FileStream) sendFinish() {
	type FsFinishedData struct {
		Complete bool `json:"complete"`
		Exitcode int  `json:"exitcode"`
	}

	fsdata := FsFinishedData{Complete: true, Exitcode: 0}
	fs.send(fsdata)
}

func jsonify(msg *service.HistoryRecord) string{
	data := map[string]any{}

	var err error
	items := msg.Item
	var val2 any

	for i := 0; i < len(items); i++ {
		val := items[i].ValueJson
		b := []byte(val)
		err = json.Unmarshal(b, &val2)
		data[items[i].Key] = val2
	}
	json_data, err := json.Marshal(data)
	check(err)
	// fmt.Println("GOT", string(json_data))
	return string(json_data)
}

func (fs *FileStream) streamHistory(msg *service.HistoryRecord) {
	fname := "wandb-history.jsonl"

	type FsChunkData struct {
		Offset int `json:"offset"`
		Content []string `json:"content"`
	}

	type FsFilesData struct {
		Files map[string]FsChunkData `json:"files"`
	}
	j := jsonify(msg)
	
	content := []string{j}
	chunk := FsChunkData{
		Offset: fs.offset,
		Content: content}
	fs.offset += 1
	files := map[string]FsChunkData{
		fname: chunk,
	}
	fsdata := FsFilesData{Files: files}
	// fmt.Println("WOULD SEND", fsdata)
	fs.send(fsdata)
}

func (fs *FileStream) streamRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_History:
		fs.streamHistory(x.History)
	case nil:
		// The field is not set.
		panic("bad2rec")
	default:
		bad := fmt.Sprintf("REC UNKNOWN type %T", x)
		panic(bad)
	}
}

func (fs *FileStream) fstreamPush(fname string, data string) {
}

func (fs *FileStream) fstreamGo() {
	defer fs.wg.Done()

	log.Debug("FSTREAM: OPEN")

	if fs.settings.Offline {
		return
	}

	fs.fstreamInit()
	for done := false; !done; {
		select {
		case msg, ok := <-fs.fstreamChan:
			if !ok {
				log.Debug("FSTREAM: NOMORE")
				done = true
				break
			}
			log.Debug("FSTREAM *******")
			log.WithFields(log.Fields{"record": msg}).Debug("FSTREAM: got msg")
			fs.streamRecord(&msg)
		}
	}
	fs.sendFinish()
	log.Debug("FSTREAM: FIN")
}
