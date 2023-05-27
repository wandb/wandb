package server

import (
	// "flag"
	// "io"
	// "google.golang.org/protobuf/reflect/protoreflect"
	"sync"
	"time"

	"bytes"
	"io/ioutil"

	"context"
	"encoding/base64"
	"fmt"

	// "google.golang.org/protobuf/proto"
	// "google.golang.org/protobuf/encoding/protojson"
	"net/http"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/pkg/service"

	log "github.com/sirupsen/logrus"
)

type Sender struct {
	senderChan    chan *service.Record
	wg            *sync.WaitGroup
	graphqlClient graphql.Client
	respondResult func(result *service.Result)
	settings      *Settings
	fstream       *FileStream
	run           *service.RunRecord
	handler       *Handler
	deferResult   *service.Result
	wgFileStream  *sync.WaitGroup
}

func NewSender(wg *sync.WaitGroup, respondResult func(result *service.Result), settings *Settings) *Sender {
	wgFileStream := sync.WaitGroup{}
	sender := Sender{
		senderChan:    make(chan *service.Record),
		wg:            wg,
		respondResult: respondResult,
		settings:      settings,
		wgFileStream:  &wgFileStream,
	}

	sender.wg.Add(1)
	go sender.senderGo()
	return &sender
}

func (sender *Sender) Stop() {
	log.Debug("SENDER: STOP")
	if sender.fstream != nil {
		sender.fstream.Stop()
		log.Debug("SENDER: shutdown stream wait")
		sender.wgFileStream.Wait()
		log.Debug("SENDER: shutdown stream done")
	}
	close(sender.senderChan)
	log.Debug("SENDER: STOP done")
}

func (sender *Sender) startRunWorkers() {
	fsPath := fmt.Sprintf("%s/files/%s/%s/%s/file_stream",
		sender.settings.BaseURL, sender.run.Entity, sender.run.Project, sender.run.RunId)
	sender.fstream = NewFileStream(sender.wgFileStream, fsPath, sender.settings)
}

func (sender *Sender) SetHandler(h *Handler) {
	sender.handler = h
}

func (sender *Sender) SendRecord(rec *service.Record) {
	control := rec.GetControl()
	if sender.settings.Offline && control != nil && !control.AlwaysSend {
		return
	}
	sender.senderChan <- rec
}

type authedTransport struct {
	key     string
	wrapped http.RoundTripper
}

func basicAuth(username, password string) string {
	auth := username + ":" + password
	return base64.StdEncoding.EncodeToString([]byte(auth))
}

func (t *authedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	req.Header.Set("User-Agent", "wandb-nexus")
	// req.Header.Set("X-WANDB-USERNAME", "jeff")
	// req.Header.Set("X-WANDB-USER-EMAIL", "jeff@wandb.com")
	return t.wrapped.RoundTrip(req)
}

func (sender *Sender) senderInit() {
	httpClient := http.Client{
		Transport: &authedTransport{
			key:     sender.settings.ApiKey,
			wrapped: http.DefaultTransport,
		},
	}
	url := fmt.Sprintf("%s/graphql", sender.settings.BaseURL)
	sender.graphqlClient = graphql.NewClient(url, &httpClient)
}

func (sender *Sender) sendNetworkStatusRequest(msg *service.NetworkStatusRequest) {
}

func (sender *Sender) sendDefer(req *service.DeferRequest) {
	log.Debug("SENDER: DEFER STOP")
	sender.Stop()
	log.Debug("SENDER: DEFER STOP done")
	log.Debug("SENDER: DEFER RESP")
	sender.respondResult(sender.deferResult)
	log.Debug("SENDER: DEFER RESP DONE")
}

func (sender *Sender) sendRunStart(req *service.RunStartRequest) {
	sender.startRunWorkers()
}

func (sender *Sender) sendHistory(msg *service.Record, history *service.HistoryRecord) {
	if sender.fstream != nil {
		sender.fstream.StreamRecord(msg)
	}
}

func (sender *Sender) sendRequest(msg *service.Record, req *service.Request) {
	switch x := req.RequestType.(type) {
	case *service.Request_NetworkStatus:
		sender.sendNetworkStatusRequest(x.NetworkStatus)
	case *service.Request_RunStart:
		sender.sendRunStart(x.RunStart)
	case *service.Request_Defer:
		sender.sendDefer(x.Defer)
	default:
	}
}

func (sender *Sender) networkSendRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_Run:
		// fmt.Println("rungot:", x)
		sender.sendRun(msg, x.Run)
	case *service.Record_Exit:
		sender.sendRunExit(msg, x.Exit)
	case *service.Record_Files:
		sender.sendFiles(msg, x.Files)
	case *service.Record_History:
		sender.sendHistory(msg, x.History)
	case *service.Record_Request:
		sender.sendRequest(msg, x.Request)
	case nil:
		// The field is not set.
		panic("bad2rec")
	default:
		bad := fmt.Sprintf("REC UNKNOWN type %T", x)
		panic(bad)
	}
}

func sendData(fname, urlPath string) error {
	method := "PUT"
	client := &http.Client{
		Timeout: time.Second * 10,
	}

	b, err := ioutil.ReadFile(fname)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(method, urlPath, bytes.NewReader(b))
	if err != nil {
		return err
	}
	// req.Header.Set("Content-Type", "application/octet-stream")
	rsp, err := client.Do(req)
	if rsp.StatusCode != http.StatusOK {
		log.Printf("Request failed with response code: %d", rsp.StatusCode)
		panic("badness")
	}
	// fmt.Println("GOTERR", rsp, err)
	check(err)
	return nil
}

func (sender *Sender) sendFiles(msg *service.Record, filesRecord *service.FilesRecord) {
	myfiles := filesRecord.GetFiles()
	for _, fi := range myfiles {
		sender.doSendFile(msg, fi)
	}
}

func (sender *Sender) doSendFile(msg *service.Record, fileItem *service.FilesItem) {
	// fmt.Println("GOTFILE", filesRecord)
	path := fileItem.GetPath()

	if sender.run == nil {
		panic("upsert run not called before send file")
	}

	ctx := context.Background()
	project := sender.run.Project
	runId := sender.run.RunId
	entity := sender.run.Entity
	fname := path
	files := []*string{&fname}

	resp, err := RunUploadUrls(
		ctx,
		sender.graphqlClient,
		project,
		files,
		&entity,
		runId,
		nil, // description
	)
	check(err)
	// func RunUploadUrls(
	//     ctx context.Context,
	//     client graphql.Client,
	//     name string,
	//     files []*string,
	//     entity *string,
	//     run string,
	//     description *string,
	// ) (*RunUploadUrlsResponse, error) {

	// got := proto.MarshalTextString(resp)
	// got := protojson.Format(resp)
	// fmt.Printf("got: %s\n", got)
	model := resp.GetModel()
	bucket := model.GetBucket()

	// runID := bucket.GetId()
	// fmt.Printf("ID: %s\n", runID)

	fileList := bucket.GetFiles()

	// headers := fileList.GetUploadHeaders()
	// fmt.Printf("HEADS: %s\n", headers)

	edges := fileList.GetEdges()
	// result := make([]*RunUploadUrlsModelProjectBucketRunFilesFileConnectionEdgesFileEdgeNodeFile, len(edges))
	result := make([]*string, len(edges))
	for i, e := range edges {
		node := e.GetNode()
		// name := node.GetName()
		url := node.GetUrl()
		// updated := node.GetUpdatedAt()
		result[i] = url
		// fmt.Printf("url: %d %s %s %s\n", i, *url, name, updated)
		err = sendData(fname, *url)
		check(err)
	}
	// fmt.Printf("got: %s\n", result)
}

func (sender *Sender) doSendDefer() {
	deferRequest := service.DeferRequest{}
	req := service.Request{
		RequestType: &service.Request_Defer{&deferRequest},
	}
	r := service.Record{
		RecordType: &service.Record_Request{&req},
		Control:    &service.Control{AlwaysSend: true},
	}
	sender.handler.HandleRecord(&r)
}

func (sender *Sender) sendRunExit(msg *service.Record, record *service.RunExitRecord) {
	// TODO: need to flush stuff before responding with exit
	runExitResult := &service.RunExitResult{}
	result := &service.Result{
		ResultType: &service.Result_ExitResult{runExitResult},
		Control:    msg.Control,
		Uuid:       msg.Uuid,
	}
	// FIXME: hack to make sure that filestream has no data before continuing
	// time.Sleep(2 * time.Second)
	// h.shutdownStream()
	sender.deferResult = result
	sender.doSendDefer()
}

func (sender *Sender) sendRun(msg *service.Record, record *service.RunRecord) {

	keepRun := *record

	// fmt.Println("SEND", record)
	ctx := context.Background()
	// resp, err := Viewer(ctx, sender.graphqlClient)
	// fmt.Println(resp, err)
	tags := []string{}
	resp, err := UpsertBucket(
		ctx, sender.graphqlClient,
		nil,           // id
		&record.RunId, // name
		nil,           // project
		nil,           // entity
		nil,           // groupName
		nil,           // description
		nil,           // displayName
		nil,           // notes
		nil,           // commit
		nil,           // config
		nil,           // host
		nil,           // debug
		nil,           // program
		nil,           // repo
		nil,           // jobType
		nil,           // state
		nil,           // sweep
		tags,          // tags []string,
		nil,           // summaryMetrics
	)
	check(err)

	displayName := *resp.UpsertBucket.Bucket.DisplayName
	projectName := resp.UpsertBucket.Bucket.Project.Name
	entityName := resp.UpsertBucket.Bucket.Project.Entity.Name
	keepRun.DisplayName = displayName
	keepRun.Project = projectName
	keepRun.Entity = entityName

	sender.run = &keepRun

	// fmt.Println("RESP::", keepRun)

	// (*UpsertBucketResponse, error) {
	/*
		id *string,
		name *string,
		project *string,
		entity *string,
		groupName *string,
		description *string,
		displayName *string,
		notes *string,
		commit *string,
		config *string,
		host *string,
		debug *bool,
		program *string,
		repo *string,
		jobType *string,
		state *string,
		sweep *string,
		tags []string,
		summaryMetrics *string,
	*/

	runResult := &service.RunUpdateResult{Run: &keepRun}
	result := &service.Result{
		ResultType: &service.Result_RunResult{runResult},
		Control:    msg.Control,
		Uuid:       msg.Uuid,
	}
	sender.respondResult(result)
}

func (sender *Sender) senderGo() {
	defer sender.wg.Done()

	log.Debug("SENDER: OPEN")
	sender.senderInit()
	for done := false; !done; {
		select {
		case msg, ok := <-sender.senderChan:
			if !ok {
				log.Debug("SENDER: NOMORE")
				done = true
				break
			}
			log.Debug("SENDER *******")
			log.WithFields(log.Fields{"record": msg}).Debug("SENDER: got msg")
			sender.networkSendRecord(msg)
			// handleLogWriter(sender, msg)
		}
	}
	log.Debug("SENDER: FIN")
}
