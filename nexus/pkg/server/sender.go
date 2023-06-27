package server

import (
	"sync"
	"time"

	"bytes"
	"os"

	"context"
	"fmt"
	"path/filepath"

	"encoding/json"
	"net/http"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"golang.org/x/exp/slog"
)

const CliVersion string = "0.0.1a1"
const MetaFilename string = "wandb-metadata.json"

type Sender struct {
	settings       *Settings
	inChan         chan *service.Record
	outChan        chan<- *service.Record
	dispatcherChan dispatchChannel
	graphqlClient  graphql.Client
	fileStream     *FileStream
	run            *service.RunRecord
	logger         *slog.Logger
}

// NewSender creates a new Sender instance
func NewSender(ctx context.Context, settings *Settings, logger *slog.Logger) *Sender {
	sender := &Sender{
		settings: settings,
		inChan:   make(chan *service.Record),
		logger:   logger,
	}
	slog.Debug("Sender: start")
	url := fmt.Sprintf("%s/graphql", settings.BaseURL)
	sender.graphqlClient = newGraphqlClient(url, settings.ApiKey)
	return sender
}

// start starts the sender
func (s *Sender) start(wg *sync.WaitGroup) {
	defer wg.Done()

	for msg := range s.inChan {
		LogRecord(s.logger, "sender: got msg", msg)
		s.sendRecord(msg)
	}
	slog.Debug("sender: started and closed")
}

// close closes the sender's resources
// func (s *Sender) close() {
// 	log.Debug("Sender: close")
// 	//close(s.fileStream.inChan)
// }

// sendRecord sends a record
func (s *Sender) sendRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_Run:
		s.sendRun(msg, x.Run)
	case *service.Record_Exit:
		s.sendExit(msg, x.Exit)
	case *service.Record_Files:
		s.sendFiles(msg, x.Files)
	case *service.Record_History:
		LogRecord(s.logger, "Sender: sendRecord", msg)
		s.sendHistory(msg, x.History)
	case *service.Record_Request:
		s.sendRequest(msg, x.Request)
	case nil:
		LogFatal(s.logger, "sender: sendRecord: nil RecordType")
	default:
		LogFatal(s.logger, fmt.Sprintf("sender: sendRecord: unexpected type %T", x))
	}
}

func (s *Sender) sendRequest(_ *service.Record, req *service.Request) {
	switch x := req.RequestType.(type) {
	case *service.Request_RunStart:
		s.sendRunStart(x.RunStart)
	case *service.Request_NetworkStatus:
		s.sendNetworkStatusRequest(x.NetworkStatus)
	case *service.Request_Defer:
		s.sendDefer(x.Defer)
	case *service.Request_Metadata:
		s.sendMetadata(x.Metadata)
	default:
	}
}

func (s *Sender) sendRunStart(_ *service.RunStartRequest) {
	fsPath := fmt.Sprintf("%s/files/%s/%s/%s/file_stream",
		s.settings.BaseURL, s.run.Entity, s.run.Project, s.run.RunId)
	s.fileStream = NewFileStream(fsPath, s.settings, s.logger)
	slog.Debug("Sender: sendRunStart: start file stream")
}

func (s *Sender) sendNetworkStatusRequest(_ *service.NetworkStatusRequest) {
}

func (s *Sender) sendMetadata(req *service.MetadataRequest) {
	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, _ := mo.Marshal(req)
	_ = os.WriteFile(filepath.Join(s.settings.FilesDir, MetaFilename), jsonBytes, 0644)

	s.sendFile(MetaFilename)
}

func (s *Sender) sendDefer(req *service.DeferRequest) {
	switch req.State {
	case service.DeferRequest_FLUSH_FS:
		slog.Debug(fmt.Sprintf("Sender: sendDefer: flush file stream: %v", req.State))
		s.fileStream.close()
		req.State++
		s.sendRequestDefer(req)
	case service.DeferRequest_END:
		slog.Debug(fmt.Sprintf("Sender: sendDefer: end = %v", req.State))
	default:
		slog.Debug(fmt.Sprintf("Sender: sendDefer: unknown state = %v", req.State))
		req.State++
		s.sendRequestDefer(req)
	}
}

func (s *Sender) sendRequestDefer(req *service.DeferRequest) {
	r := service.Record{
		RecordType: &service.Record_Request{Request: &service.Request{
			RequestType: &service.Request_Defer{Defer: req},
		}},
		Control: &service.Control{AlwaysSend: true},
	}
	s.outChan <- &r
}

func (s *Sender) parseConfigUpdate(config *service.ConfigRecord) map[string]interface{} {
	datas := make(map[string]interface{})

	// TODO: handle deletes and nested key updates
	for _, d := range config.GetUpdate() {
		j := d.GetValueJson()
		var data interface{}
		err := json.Unmarshal([]byte(j), &data)
		if err != nil {
			LogFatalError(s.logger, "unmarshal problem", err)
		}
		datas[d.GetKey()] = data
	}
	return datas
}

func (s *Sender) updateConfigTelemetry(config map[string]interface{}) {
	got := config["_wandb"]
	switch v := got.(type) {
	case map[string]interface{}:
		v["cli_version"] = CliVersion
	default:
		LogFatal(s.logger, fmt.Sprintf("can not parse config _wandb, saw: %v", v))
	}
}

func (s *Sender) getValueConfig(config map[string]interface{}) map[string]map[string]interface{} {
	datas := make(map[string]map[string]interface{})

	for key, elem := range config {
		datas[key] = make(map[string]interface{})
		datas[key]["value"] = elem
	}
	return datas
}

func (s *Sender) sendRun(msg *service.Record, record *service.RunRecord) {

	run, ok := proto.Clone(record).(*service.RunRecord)
	if !ok {
		LogFatal(s.logger, "error")
	}

	config := s.parseConfigUpdate(record.Config)
	s.updateConfigTelemetry(config)
	valueConfig := s.getValueConfig(config)
	configJson, err := json.Marshal(valueConfig)
	if err != nil {
		LogFatalError(s.logger, "marshal prob", err)
	}
	configString := string(configJson)

	ctx := context.Background()
	var tags []string
	resp, err := UpsertBucket(
		ctx, s.graphqlClient,
		nil,           // id
		&record.RunId, // name
		nil,           // project
		nil,           // entity
		nil,           // groupName
		nil,           // description
		nil,           // displayName
		nil,           // notes
		nil,           // commit
		&configString, // config
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
	if err != nil {
		LogError(s.logger, "error upserting bucket", err)
	}

	run.DisplayName = *resp.UpsertBucket.Bucket.DisplayName
	run.Project = resp.UpsertBucket.Bucket.Project.Name
	run.Entity = resp.UpsertBucket.Bucket.Project.Entity.Name

	s.run = run
	result := &service.Result{
		ResultType: &service.Result_RunResult{RunResult: &service.RunUpdateResult{Run: run}},
		Control:    msg.Control,
		Uuid:       msg.Uuid,
	}
	LogResult(s.logger, "sending run result ", result)
	s.dispatcherChan.Deliver(result)
}

func (s *Sender) sendHistory(msg *service.Record, _ *service.HistoryRecord) {
	LogRecord(s.logger, "sending history result ", msg)
	if s.fileStream != nil {
		s.fileStream.stream(msg)
	}
}

func (s *Sender) sendExit(msg *service.Record, _ *service.RunExitRecord) {
	// send exit via filestream
	LogRecord(s.logger, "sending run exit result ", msg)
	s.fileStream.stream(msg)

	result := &service.Result{
		ResultType: &service.Result_ExitResult{ExitResult: &service.RunExitResult{}},
		Control:    msg.Control,
		Uuid:       msg.Uuid,
	}
	s.dispatcherChan.Deliver(result)
	//RequestType: &service.Request_Defer{Defer: &service.DeferRequest{State: service.DeferRequest_BEGIN}}
	req := &service.Request{RequestType: &service.Request_Defer{Defer: &service.DeferRequest{State: service.DeferRequest_BEGIN}}}
	rec := &service.Record{RecordType: &service.Record_Request{Request: req}, Control: msg.Control, Uuid: msg.Uuid}
	s.sendRecord(rec)
}

func (s *Sender) sendFiles(msg *service.Record, filesRecord *service.FilesRecord) {
	files := filesRecord.GetFiles()
	for _, file := range files {
		s.sendFile(file.GetPath())
	}
}

func sendData(fileName, urlPath string, logger *slog.Logger) error {
	client := &http.Client{
		Timeout: time.Second * 10,
	}

	b, err := os.ReadFile(fileName)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(http.MethodPut, urlPath, bytes.NewReader(b))
	if err != nil {
		return err
	}
	rsp, err := client.Do(req)
	if rsp.StatusCode != http.StatusOK {
		LogFatal(logger, fmt.Sprintf("Request failed with response code: %d", rsp.StatusCode))
	}
	if err != nil {
		return err
	}
	return nil
}

func (s *Sender) sendFile(path string) {

	fullPath := filepath.Join(s.settings.FilesDir, path)
	if s.run == nil {
		LogFatal(s.logger, "upsert run not called before send db")
	}

	entity := s.run.Entity
	resp, err := RunUploadUrls(
		context.Background(),
		s.graphqlClient,
		s.run.Project,
		[]*string{&path},
		&entity,
		s.run.RunId,
		nil, // description
	)
	if err != nil {
		LogError(s.logger, "error getting upload urls", err)
	}

	edges := resp.GetModel().GetBucket().GetFiles().GetEdges()
	for _, e := range edges {
		url := e.GetNode().GetUrl()
		if err = sendData(fullPath, *url, s.logger); err != nil {
			LogError(s.logger, "error sending data", err)
		}
	}
}
