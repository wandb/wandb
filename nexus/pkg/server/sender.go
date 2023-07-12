package server

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const (
	CliVersion   = "0.0.1a1"
	MetaFilename = "wandb-metadata.json"
)

// Sender is the sender for a stream it handles the incoming messages and sends to the server
// or/and to the dispatcher/handler
type Sender struct {
	// ctx is the context for the handler
	ctx context.Context

	// inChan is the channel for incoming messages
	inChan chan *service.Record

	//	outChan is the channel for outgoing messages
	outChan chan<- *service.Record

	// dispatcherChan is the channel for dispatcher messages
	dispatcherChan chan<- *service.Result

	// graphqlClient is the graphql client
	graphqlClient graphql.Client

	// fileStream is the file stream
	fileStream *FileStream

	// uploader is the file uploader
	uploader *Uploader

	// run is the run record
	run *service.RunRecord

	// logger is the logger for the sender
	logger *slog.Logger

	// settings is the settings for the sender
	settings *service.Settings
}

// NewSender creates a new Sender with the given settings
func NewSender(ctx context.Context, settings *service.Settings, logger *slog.Logger) *Sender {
	url := fmt.Sprintf("%s/graphql", settings.GetBaseUrl().GetValue())
	apiKey := settings.GetApiKey().GetValue()
	return &Sender{
		ctx:           ctx,
		settings:      settings,
		inChan:        make(chan *service.Record),
		logger:        logger,
		graphqlClient: newGraphqlClient(url, apiKey, logger),
	}
}

// do sending of messages to the server
func (s *Sender) do() {

	defer func() {
		close(s.dispatcherChan)
		s.logger.Info("sender: closed", "stream_id", s.settings.RunId)
	}()

	s.logger.Info("sender: started", "stream_id", s.settings.RunId)
	for msg := range s.inChan {
		s.sendRecord(msg)
	}
}

// sendRecord sends a record
func (s *Sender) sendRecord(msg *service.Record) {

	s.logger.Debug("sender: sendRecord", "msg", msg, "stream_id", s.settings.RunId)
	switch x := msg.RecordType.(type) {
	case *service.Record_Run:
		s.sendRun(msg, x.Run)
	case *service.Record_Exit:
		s.sendExit(msg, x.Exit)
	case *service.Record_Files:
		s.sendFiles(msg, x.Files)
	case *service.Record_History:
		s.sendHistory(msg, x.History)
	case *service.Record_Request:
		s.sendRequest(msg, x.Request)
	case nil:
		err := fmt.Errorf("sender: sendRecord: nil RecordType")
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
	default:
		err := fmt.Errorf("sender: sendRecord: unexpected type %T", x)
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
	}
}

// sendRequest sends a request
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
		// TODO: handle errors
	}
}

// sendRun starts up all the resources for a run
func (s *Sender) sendRunStart(_ *service.RunStartRequest) {
	fsPath := fmt.Sprintf("%s/files/%s/%s/%s/file_stream",
		s.settings.GetBaseUrl().GetValue(), s.run.Entity, s.run.Project, s.run.RunId)
	s.fileStream = NewFileStream(fsPath, s.settings, s.logger)
	s.fileStream.Start()
	s.uploader = NewUploader(s.ctx, s.logger)
}

func (s *Sender) sendNetworkStatusRequest(_ *service.NetworkStatusRequest) {
}

func (s *Sender) sendMetadata(req *service.MetadataRequest) {
	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, _ := mo.Marshal(req)
	_ = os.WriteFile(filepath.Join(s.settings.GetFilesDir().GetValue(), MetaFilename), jsonBytes, 0644)
	s.sendFile(MetaFilename)
}

func (s *Sender) sendDefer(req *service.DeferRequest) {
	switch req.State {
	case service.DeferRequest_FLUSH_FP:
		s.uploader.Close()
		req.State++
		s.sendRequestDefer(req)
	case service.DeferRequest_FLUSH_FS:
		s.fileStream.Close()
		req.State++
		s.sendRequestDefer(req)
	case service.DeferRequest_END:
		close(s.outChan)
	default:
		req.State++
		s.sendRequestDefer(req)
	}
}

func (s *Sender) sendRequestDefer(req *service.DeferRequest) {
	rec := &service.Record{
		RecordType: &service.Record_Request{Request: &service.Request{
			RequestType: &service.Request_Defer{Defer: req},
		}},
		Control: &service.Control{AlwaysSend: true},
	}
	s.outChan <- rec
}

func (s *Sender) parseConfigUpdate(config *service.ConfigRecord) map[string]interface{} {
	datas := make(map[string]interface{})

	// TODO: handle deletes and nested key updates
	for _, d := range config.GetUpdate() {
		j := d.GetValueJson()
		var data interface{}
		if err := json.Unmarshal([]byte(j), &data); err != nil {
			s.logger.Error("unmarshal problem", "err", err, "stream_id", s.settings.RunId)
			panic(err)
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
		err := fmt.Errorf("can not parse config _wandb, saw: %v", v)
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
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
		err := fmt.Errorf("sender: sendRun: failed to clone RunRecord")
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
	}

	config := s.parseConfigUpdate(record.Config)
	s.updateConfigTelemetry(config)
	valueConfig := s.getValueConfig(config)
	configJson, err := json.Marshal(valueConfig)
	if err != nil {
		err = fmt.Errorf("sender: sendRun: failed to marshal config: %s", err)
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
	}
	configString := string(configJson)

	var tags []string
	resp, err := UpsertBucket(
		s.ctx,           // ctx
		s.graphqlClient, // client
		nil,             // id
		&record.RunId,   // name
		nil,             // project
		nil,             // entity
		nil,             // groupName
		nil,             // description
		nil,             // displayName
		nil,             // notes
		nil,             // commit
		&configString,   // config
		nil,             // host
		nil,             // debug
		nil,             // program
		nil,             // repo
		nil,             // jobType
		nil,             // state
		nil,             // sweep
		tags,            // tags []string,
		nil,             // summaryMetrics
	)
	if err != nil {
		err = fmt.Errorf("sender: sendRun: failed to upsert bucket: %s", err)
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
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
	s.dispatcherChan <- result
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(msg *service.Record, _ *service.HistoryRecord) {
	if s.fileStream != nil {
		s.fileStream.StreamRecord(msg)
	}
}

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(msg *service.Record, _ *service.RunExitRecord) {

	s.fileStream.StreamRecord(msg)
	result := &service.Result{
		ResultType: &service.Result_ExitResult{ExitResult: &service.RunExitResult{}},
		Control:    msg.Control,
		Uuid:       msg.Uuid,
	}
	s.dispatcherChan <- result
	req := &service.Request{RequestType: &service.Request_Defer{Defer: &service.DeferRequest{State: service.DeferRequest_BEGIN}}}
	rec := &service.Record{RecordType: &service.Record_Request{Request: req}, Control: msg.Control, Uuid: msg.Uuid}
	s.sendRecord(rec)
}

// sendFiles iterates over the files in the FilesRecord and sends them to
func (s *Sender) sendFiles(_ *service.Record, filesRecord *service.FilesRecord) {
	files := filesRecord.GetFiles()
	for _, file := range files {
		s.sendFile(file.GetPath())
	}
}

// sendFile sends a file to the server
func (s *Sender) sendFile(path string) {
	if s.run == nil {
		err := fmt.Errorf("sender: sendFile: run not set")
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
	}

	entity := s.run.Entity
	resp, err := RunUploadUrls(
		s.ctx,
		s.graphqlClient,
		s.run.Project,
		[]*string{&path},
		&entity,
		s.run.RunId,
		nil,
	)
	if err != nil {
		err = fmt.Errorf("sender: sendFile: failed to get upload urls: %s", err)
		s.logger.Error("sender received error", "err", err, "stream_id", s.settings.RunId)
		panic(err)
	}

	fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), path)
	edges := resp.GetModel().GetBucket().GetFiles().GetEdges()
	for _, e := range edges {
		task := &UploadTask{fullPath, *e.GetNode().GetUrl()}
		s.uploader.AddTask(task)
	}
}
