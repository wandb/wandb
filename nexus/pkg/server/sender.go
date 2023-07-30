package server

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/wandb/wandb/nexus/internal/gql"
	"github.com/wandb/wandb/nexus/internal/uploader"
	"github.com/wandb/wandb/nexus/pkg/artifacts"
	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/pkg/service"
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

	// logger is the logger for the sender
	logger *observability.NexusLogger

	// settings is the settings for the sender
	settings *service.Settings

	//	recordChan is the channel for outgoing messages
	recordChan chan *service.Record

	// resultChan is the channel for dispatcher messages
	resultChan chan *service.Result

	// graphqlClient is the graphql client
	graphqlClient graphql.Client

	// fileStream is the file stream
	fileStream *FileStream

	// uploader is the file uploader
	uploader *uploader.Uploader

	// RunRecord is the run record
	RunRecord *service.RunRecord
}

func emptyAsNil(s *string) *string {
	if s == nil {
		return nil
	}
	if *s == "" {
		return nil
	}
	return s
}

// NewSender creates a new Sender with the given settings
func NewSender(ctx context.Context, settings *service.Settings, logger *observability.NexusLogger) *Sender {
	url := fmt.Sprintf("%s/graphql", settings.GetBaseUrl().GetValue())
	apiKey := settings.GetApiKey().GetValue()
	return &Sender{
		ctx:           ctx,
		settings:      settings,
		logger:        logger,
		graphqlClient: newGraphqlClient(url, apiKey, logger),
	}
}

// do sending of messages to the server
func (s *Sender) do(inChan <-chan *service.Record) (<-chan *service.Result, <-chan *service.Record) {
	s.logger.Info("sender: started", "stream_id", s.settings.RunId)
	s.recordChan = make(chan *service.Record, BufferSize)
	s.resultChan = make(chan *service.Result, BufferSize)

	go func() {
		for record := range inChan {
			s.sendRecord(record)
		}
		s.logger.Info("sender: closed", "stream_id", s.settings.RunId)
	}()
	return s.resultChan, s.recordChan
}

// sendRecord sends a record
func (s *Sender) sendRecord(record *service.Record) {
	s.logger.Debug("sender: sendRecord", "record", record, "stream_id", s.settings.RunId)
	switch x := record.RecordType.(type) {
	case *service.Record_Run:
		s.sendRun(record, x.Run)
	case *service.Record_Exit:
		s.sendExit(record, x.Exit)
	case *service.Record_Alert:
		s.sendAlert(record, x.Alert)
	case *service.Record_Files:
		s.sendFiles(record, x.Files)
	case *service.Record_History:
		s.sendHistory(record, x.History)
	case *service.Record_Stats:
		s.sendSystemMetrics(record, x.Stats)
	case *service.Record_OutputRaw:
		s.sendOutputRaw(record, x.OutputRaw)
	case *service.Record_Request:
		s.sendRequest(record, x.Request)
	case nil:
		err := fmt.Errorf("sender: sendRecord: nil RecordType")
		s.logger.CaptureFatalAndPanic("sender: sendRecord: nil RecordType", err)
	default:
		err := fmt.Errorf("sender: sendRecord: unexpected type %T", x)
		s.logger.CaptureFatalAndPanic("sender: sendRecord: unexpected type", err)
	}
}

// sendRequest sends a request
func (s *Sender) sendRequest(record *service.Record, request *service.Request) {

	switch x := request.RequestType.(type) {
	case *service.Request_RunStart:
		s.sendRunStart(x.RunStart)
	case *service.Request_NetworkStatus:
		s.sendNetworkStatusRequest(x.NetworkStatus)
	case *service.Request_Defer:
		s.sendDefer(x.Defer)
	case *service.Request_Metadata:
		s.sendMetadata(x.Metadata)
	case *service.Request_LogArtifact:
		s.sendLogArtifact(record, x.LogArtifact)
	default:
		// TODO: handle errors
	}
}

// sendRun starts up all the resources for a run
func (s *Sender) sendRunStart(_ *service.RunStartRequest) {
	if !s.settings.GetXOffline().GetValue() {
		fsPath := fmt.Sprintf("%s/files/%s/%s/%s/file_stream",
			s.settings.GetBaseUrl().GetValue(), s.RunRecord.Entity, s.RunRecord.Project, s.RunRecord.RunId)
		s.fileStream = NewFileStream(fsPath, s.settings, s.logger)
	}
	s.uploader = uploader.NewUploader(s.ctx, s.logger)
}

func (s *Sender) sendNetworkStatusRequest(_ *service.NetworkStatusRequest) {
}

func (s *Sender) sendMetadata(request *service.MetadataRequest) {
	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, _ := mo.Marshal(request)
	_ = os.WriteFile(filepath.Join(s.settings.GetFilesDir().GetValue(), MetaFilename), jsonBytes, 0644)
	s.sendFile(MetaFilename)
}

func (s *Sender) sendDefer(request *service.DeferRequest) {
	switch request.State {
	case service.DeferRequest_FLUSH_FP:
		s.uploader.Close()
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_FS:
		if s.fileStream != nil {
			s.fileStream.Close()
		}
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_END:
		close(s.recordChan)
		close(s.resultChan)
	default:
		request.State++
		s.sendRequestDefer(request)
	}
}

func (s *Sender) sendRequestDefer(request *service.DeferRequest) {
	rec := &service.Record{
		RecordType: &service.Record_Request{Request: &service.Request{
			RequestType: &service.Request_Defer{Defer: request},
		}},
		Control: &service.Control{AlwaysSend: true},
	}
	s.recordChan <- rec
}

func (s *Sender) parseConfigUpdate(config *service.ConfigRecord) map[string]interface{} {
	datas := make(map[string]interface{})

	// TODO: handle deletes and nested key updates
	for _, d := range config.GetUpdate() {
		j := d.GetValueJson()
		var data interface{}
		if err := json.Unmarshal([]byte(j), &data); err != nil {
			s.logger.CaptureFatalAndPanic("unmarshal problem", err)
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
		s.logger.CaptureFatalAndPanic("sender received error", err)
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

func (s *Sender) sendRun(record *service.Record, run *service.RunRecord) {

	var ok bool
	s.RunRecord, ok = proto.Clone(run).(*service.RunRecord)
	if !ok {
		err := fmt.Errorf("sender: sendRun: failed to clone RunRecord")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	config := s.parseConfigUpdate(run.Config)
	s.updateConfigTelemetry(config)
	valueConfig := s.getValueConfig(config)
	configJson, err := json.Marshal(valueConfig)
	if err != nil {
		err = fmt.Errorf("sender: sendRun: failed to marshal config: %s", err)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}
	configString := string(configJson)

	var tags []string
	data, err := gql.UpsertBucket(
		s.ctx,                    // ctx
		s.graphqlClient,          // client
		nil,                      // id
		&run.RunId,               // name
		emptyAsNil(&run.Project), // project
		emptyAsNil(&run.Entity),  // entity
		nil,                      // groupName
		nil,                      // description
		nil,                      // displayName
		nil,                      // notes
		nil,                      // commit
		&configString,            // config
		nil,                      // host
		nil,                      // debug
		nil,                      // program
		nil,                      // repo
		nil,                      // jobType
		nil,                      // state
		nil,                      // sweep
		tags,                     // tags []string,
		nil,                      // summaryMetrics
	)
	if err != nil {
		err = fmt.Errorf("sender: sendRun: failed to upsert bucket: %s", err)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	s.RunRecord.DisplayName = *data.UpsertBucket.Bucket.DisplayName
	s.RunRecord.Project = data.UpsertBucket.Bucket.Project.Name
	s.RunRecord.Entity = data.UpsertBucket.Bucket.Project.Entity.Name

	result := &service.Result{
		ResultType: &service.Result_RunResult{
			RunResult: &service.RunUpdateResult{Run: s.RunRecord},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.resultChan <- result
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(record *service.Record, _ *service.HistoryRecord) {
	if s.fileStream != nil {
		s.fileStream.StreamRecord(record)
	}
}

func (s *Sender) sendSystemMetrics(record *service.Record, _ *service.StatsRecord) {
	if s.fileStream != nil {
		s.fileStream.StreamRecord(record)
	}
}

func (s *Sender) sendOutputRaw(record *service.Record, outputRaw *service.OutputRawRecord) {
	// TODO: match logic handling of lines to the one in the python version
	// - handle carriage returns (for tqdm-like progress bars)
	// - handle caching multiple (non-new lines) and sending them in one chunk
	// - handle lines longer than ~60_000 characters

	// ignore empty "new lines"
	if outputRaw.Line == "\n" {
		return
	}
	t := time.Now().UTC().Format(time.RFC3339)
	outputRaw.Line = fmt.Sprintf("%s %s", t, outputRaw.Line)
	if outputRaw.OutputType == service.OutputRawRecord_STDERR {
		outputRaw.Line = fmt.Sprintf("ERROR %s", outputRaw.Line)
	}

	if s.fileStream != nil {
		s.fileStream.StreamRecord(record)
	}
}

func (s *Sender) sendAlert(_ *service.Record, alert *service.AlertRecord) {

	// TODO: handle invalid alert levels
	severity := gql.AlertSeverity(alert.Level)
	waitDuration := time.Duration(alert.WaitDuration) * time.Second

	data, err := gql.NotifyScriptableRunAlert(
		s.ctx,
		s.graphqlClient,
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
		alert.Title,
		alert.Text,
		&severity,
		&waitDuration,
	)
	if err != nil {
		err = fmt.Errorf("sender: sendAlert: failed to notify scriptable run alert: %s", err)
		s.logger.CaptureError("sender received error", err)
	} else {
		s.logger.Info("sender: sendAlert: notified scriptable run alert", "data", data)
	}

}

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(record *service.Record, _ *service.RunExitRecord) {
	if s.fileStream != nil {
		s.fileStream.StreamRecord(record)
	}
	result := &service.Result{
		ResultType: &service.Result_ExitResult{ExitResult: &service.RunExitResult{}},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.resultChan <- result

	request := &service.Request{RequestType: &service.Request_Defer{
		Defer: &service.DeferRequest{State: service.DeferRequest_BEGIN}},
	}
	rec := &service.Record{
		RecordType: &service.Record_Request{Request: request},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	// s.sendRecord(rec)
	s.recordChan <- rec
}

// sendFiles iterates over the files in the FilesRecord and sends them to
func (s *Sender) sendFiles(_ *service.Record, filesRecord *service.FilesRecord) {
	files := filesRecord.GetFiles()
	for _, file := range files {
		s.sendFile(file.GetPath())
	}
}

// sendFile sends a file to the server
func (s *Sender) sendFile(name string) {
	if s.RunRecord == nil {
		err := fmt.Errorf("sender: sendFile: RunRecord not set")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	data, err := gql.RunUploadUrls(
		s.ctx,
		s.graphqlClient,
		s.RunRecord.Project,
		[]*string{&name},
		&s.RunRecord.Entity,
		s.RunRecord.RunId,
		nil,
	)
	if err != nil {
		err = fmt.Errorf("sender: sendFile: failed to get upload urls: %s", err)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), name)
	edges := data.GetModel().GetBucket().GetFiles().GetEdges()
	for _, e := range edges {
		task := &uploader.UploadTask{Path: fullPath, Url: *e.GetNode().GetUrl()}
		s.uploader.AddTask(task)
	}
}

func (s *Sender) sendLogArtifact(record *service.Record, msg *service.LogArtifactRequest) {
	saver := artifacts.ArtifactSaver{
		Ctx:           s.ctx,
		Logger:        s.logger,
		Artifact:      msg.Artifact,
		GraphqlClient: s.graphqlClient,
		Uploader:      s.uploader,
	}
	saverResult, err := saver.Save()
	if err != nil {
		s.logger.CaptureFatalAndPanic("sender: sendLogArtifact: save failure", err)
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_LogArtifactResponse{
					LogArtifactResponse: &service.LogArtifactResponse{
						ArtifactId: saverResult.ArtifactId,
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.resultChan <- result
}
