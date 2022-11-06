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

	httpClient http.Client
}

func NewFileStream(wg *sync.WaitGroup, fstreamPath string) *FileStream {
	fs := FileStream{
		wg:          wg,
		fstreamPath: fstreamPath,
		fstreamChan: make(chan service.Record)}
	wg.Add(1)
	go fs.fstreamGo()
	return &fs
}

func (fs *FileStream) Stop() {
	// Must be called from handler
	close(fs.fstreamChan)
}

func (fs *FileStream) fstreamInit() {
	key := os.Getenv("WANDB_API_KEY")
	if key == "" {
		err := fmt.Errorf("must set WANDB_API_KEY=<wandb api key>")
		panic(err)
		return
	}

	httpClient := http.Client{
		Transport: &authedTransport{
			key:     key,
			wrapped: http.DefaultTransport,
		},
	}
	fs.httpClient = httpClient
}

func (fs *FileStream) fstreamFinish() {
	type FsData struct {
		Complete bool `json:"complete"`
		Exitcode int  `json:"exitcode"`
	}
	fsdata := FsData{Complete: true, Exitcode: 0}
	json_data, err := json.Marshal(fsdata)

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

func (fs *FileStream) fstreamPush(fname string, data string) {
}

func (fs *FileStream) fstreamGo() {
	defer fs.wg.Done()

	log.Debug("FSTREAM: OPEN")
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
		}
	}
	fs.fstreamFinish()
	log.Debug("FSTREAM: FIN")
}
