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
	MetaFilename = "wandb-metadata.json"
	NexusVersion = "0.0.1a2"
)

type ResumeState struct {
	Resumed          bool
	ResumeStep       int64
	ResumeRuntime    time.Time
	Summary          *service.SummaryRecord
	Config           *service.ConfigRecord
	FileStreamOffset map[chunkFile]int
	Error            service.ErrorInfo
}

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

	// resumeState is the resume state
	resumeState *ResumeState

	// Keep track of summary which is being updated incrementally
	summaryMap map[string]*service.SummaryItem

	// Keep track of config which is being updated incrementally
	configMap map[string]interface{}
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
		summaryMap:    make(map[string]*service.SummaryItem),
		configMap:     make(map[string]interface{}),
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
	case *service.Record_Summary:
		s.sendSummary(record, x.Summary)
	case *service.Record_Config:
		s.sendConfig(record, x.Config)
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
		for k, v := range s.resumeState.FileStreamOffset {
			s.fileStream.SetOffset(k, v)
		}
		s.fileStream.Start()
	}
	s.uploader = uploader.NewUploader(s.ctx, s.logger)
	s.uploader.Start()
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
		if s.uploader != nil {
			s.uploader.Close()
		}
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

func (s *Sender) checkAndUpdateResumeState(run *service.RunRecord) error {
	s.resumeState = &ResumeState{}

	// There was no resume status set, so we don't need to do anything
	if s.settings.GetResume().GetValue() == "" {
		return nil
	}

	// If we couldn't get the resume status, we should fail if resume is set
	data, err := gql.RunResumeStatus(s.ctx, s.graphqlClient, &run.Project, emptyAsNil(&run.Entity), run.RunId)
	if err != nil {
		err = fmt.Errorf("failed to get run resume status: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		s.resumeState.Error = service.ErrorInfo{
			Message: err.Error(),
			Code:    service.ErrorInfo_INTERNAL,
		}
		return err
	}

	// If we get that the run is not a resume run, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	// If we get that the run is a resume run, we should fail if resume is set to never
	// for any other case of resume status, we should continue to process the resume response
	if data.GetModel() == nil || data.GetModel().GetBucket() == nil {
		if s.settings.GetResume().GetValue() == "must" {
			err = fmt.Errorf("You provided an invalid value for the `resume` argument. "+
				"The value 'must' is not a valid option for resuming a run (%s/%s) that does not exist. "+
				"Please check your inputs and try again with a valid run ID. "+
				"If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`.\n", run.Project, run.RunId)
			s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
			s.resumeState.Error = service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_USAGE,
			}
			return err
		}
		return nil
	} else if s.settings.GetResume().GetValue() == "never" {
		err = fmt.Errorf("You provided an invalid value for the `resume` argument. "+
			"The value 'never' is not a valid option for resuming a run (%s/%s) that already exists. "+
			"Please check your inputs and try again with a valid value for the `resume` argument.\n", run.Project, run.RunId)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		s.resumeState.Error = service.ErrorInfo{
			Message: err.Error(),
			Code:    service.ErrorInfo_USAGE,
		}
		return err
	}

	var rerr error
	bucket := data.GetModel().GetBucket()
	s.resumeState.Resumed = true

	var historyTail []string
	var historyTailMap map[string]interface{}
	if err = json.Unmarshal([]byte(*bucket.GetHistoryTail()), &historyTail); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		rerr = err
		// TODO: verify the list is not empty and has one element
	} else if err = json.Unmarshal([]byte(historyTail[0]), &historyTailMap); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail map: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		rerr = err
	} else {
		if step, ok := historyTailMap["_step"].(float64); ok {
			s.resumeState.ResumeStep = int64(step)
		}
	}

	if s.resumeState.FileStreamOffset == nil {
		s.resumeState.FileStreamOffset = make(map[chunkFile]int)
	}
	s.resumeState.FileStreamOffset[historyChunk] = *bucket.GetHistoryLineCount()
	s.resumeState.FileStreamOffset[eventsChunk] = *bucket.GetEventsLineCount()
	s.resumeState.FileStreamOffset[outputChunk] = *bucket.GetLogLineCount()

	// If we are unable to parse the config, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	var summary map[string]interface{}
	if err = json.Unmarshal([]byte(*bucket.GetSummaryMetrics()), &summary); err != nil {
		err = fmt.Errorf("failed to unmarshal summary metrics: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		rerr = err
	} else {
		summaryRecord := service.SummaryRecord{}
		for key, value := range summary {
			jsonValue, _ := json.Marshal(value)
			summaryRecord.Update = append(summaryRecord.Update, &service.SummaryItem{
				Key:       key,
				ValueJson: string(jsonValue),
			})
		}
		s.resumeState.Summary = &summaryRecord
	}

	var config map[string]interface{}
	if err = json.Unmarshal([]byte(*bucket.GetConfig()), &config); err != nil {
		err = fmt.Errorf("sender: checkAndUpdateResumeState: failed to unmarshal config: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		rerr = err
	} else {
		for key, value := range config {
			switch v := value.(type) {
			case map[string]interface{}:
				s.configMap[key] = v["value"]
			default:
				s.logger.Error("sender: checkAndUpdateResumeState: config value is not a map[string]interface{}")
			}
		}
	}
	if rerr != nil && s.settings.GetResume().GetValue() == "must" {
		err = fmt.Errorf("failed to parse resume state but resume is set to must")
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		s.resumeState.Error = service.ErrorInfo{
			Message: err.Error(),
			Code:    service.ErrorInfo_INTERNAL,
		}
		return err
	}
	return nil
}

// updateConfig updates the config map with the config record
func (s *Sender) updateConfig(configRecord *service.ConfigRecord) {
	// TODO: handle nested key updates and deletes
	for _, d := range configRecord.GetUpdate() {
		var value interface{}
		if err := json.Unmarshal([]byte(d.GetValueJson()), &value); err != nil {
			s.logger.CaptureError("unmarshal problem", err)
			continue
		}
		s.configMap[d.GetKey()] = value
	}
	for _, d := range configRecord.GetRemove() {
		delete(s.configMap, d.GetKey())
	}
}

// updateTelemetry updates the config map with the telemetry record
func (s *Sender) updateTelemetry(configRecord *service.TelemetryRecord) {
	if configRecord == nil {
		return
	}

	if _, ok := s.configMap["_wandb"]; !ok {
		s.configMap["_wandb"] = make(map[string]interface{})
	}

	switch v := s.configMap["_wandb"].(type) {
	case map[string]interface{}:
		v["nexus_version"] = NexusVersion
		if configRecord.CliVersion != "" {
			v["cli_version"] = configRecord.CliVersion
		}
		if configRecord.PythonVersion != "" {
			v["python_version"] = configRecord.PythonVersion
		}

		// todo: add the rest of the telemetry from configRecord
	default:
		err := fmt.Errorf("can not parse config _wandb, saw: %v", v)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}
}

// serializeConfig serializes the config map to a json string
// that can be sent to the server
func (s *Sender) serializeConfig() string {
	valueConfig := make(map[string]map[string]interface{})
	for key, elem := range s.configMap {
		valueConfig[key] = make(map[string]interface{})
		valueConfig[key]["value"] = elem
	}
	configJson, err := json.Marshal(valueConfig)
	if err != nil {
		err = fmt.Errorf("failed to marshal config: %s", err)
		s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
	}
	configString := string(configJson)

	return configString
}

func (s *Sender) sendRun(record *service.Record, run *service.RunRecord) {

	var ok bool
	s.RunRecord, ok = proto.Clone(run).(*service.RunRecord)
	if !ok {
		err := fmt.Errorf("failed to clone RunRecord")
		s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
	}

	if err := s.checkAndUpdateResumeState(s.RunRecord); err != nil {
		s.logger.Error("sender: sendRun: failed to checkAndUpdateResumeState", "error", err)
		result := &service.Result{
			ResultType: &service.Result_RunResult{
				RunResult: &service.RunUpdateResult{
					Error: &s.resumeState.Error,
				},
			},
			Control: record.Control,
			Uuid:    record.Uuid,
		}
		s.resultChan <- result
		return
	}

	s.updateConfig(run.Config)
	s.updateTelemetry(run.Telemetry)
	config := s.serializeConfig()

	var tags []string
	tags = append(tags, run.Tags...)

	var commit, repo string
	git := run.GetGit()
	if git != nil {
		commit = git.GetCommit()
		repo = git.GetRemoteUrl()
	}

	program := s.settings.GetProgram().GetValue()
	data, err := gql.UpsertBucket(
		s.ctx,                        // ctx
		s.graphqlClient,              // client
		nil,                          // id
		&run.RunId,                   // name
		emptyAsNil(&run.Project),     // project
		emptyAsNil(&run.Entity),      // entity
		emptyAsNil(&run.RunGroup),    // groupName
		nil,                          // description
		emptyAsNil(&run.DisplayName), // displayName
		emptyAsNil(&run.Notes),       // notes
		emptyAsNil(&commit),          // commit
		&config,                      // config
		emptyAsNil(&run.Host),        // host
		nil,                          // debug
		emptyAsNil(&program),         // program
		emptyAsNil(&repo),            // repo
		emptyAsNil(&run.JobType),     // jobType
		nil,                          // state
		nil,                          // sweep
		tags,                         // tags []string,
		nil,                          // summaryMetrics
	)
	if err != nil {
		err = fmt.Errorf("failed to upsert bucket: %s", err)
		s.logger.Error("sender: sendRun:", "error", err)
		result := &service.Result{
			ResultType: &service.Result_RunResult{
				RunResult: &service.RunUpdateResult{
					Error: &service.ErrorInfo{
						Message: err.Error(),
						Code:    service.ErrorInfo_INTERNAL,
					},
				},
			},
			Control: record.Control,
			Uuid:    record.Uuid,
		}
		s.resultChan <- result
		return
	}

	s.RunRecord.DisplayName = *data.UpsertBucket.Bucket.DisplayName
	s.RunRecord.Project = data.UpsertBucket.Bucket.Project.Name
	s.RunRecord.Entity = data.UpsertBucket.Bucket.Project.Entity.Name
	s.RunRecord.Resumed = s.resumeState.Resumed
	// if we are resuming, we need to update the starting step
	// to be the next step after the last step we ran
	if s.RunRecord.Resumed && s.resumeState.ResumeStep > 0 {
		s.RunRecord.StartingStep = s.resumeState.ResumeStep + 1
	}
	if s.resumeState.Summary != nil {
		s.RunRecord.Summary = s.resumeState.Summary
	}

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

func (s *Sender) sendSummary(_ *service.Record, summary *service.SummaryRecord) {
	// TODO(network): buffer summary sending for network efficiency until we can send only updates
	// TODO(compat): handle deletes, nested keys
	// TODO(compat): write summary file

	// track each key in the in memory summary store
	// TODO(memory): avoid keeping summary for all distinct keys
	for _, item := range summary.Update {
		s.summaryMap[item.Key] = item
	}

	// build list of summary items from the map
	var summaryItems []*service.SummaryItem
	for _, v := range s.summaryMap {
		summaryItems = append(summaryItems, v)
	}

	// build a full summary record to send
	record := &service.Record{
		RecordType: &service.Record_Summary{
			Summary: &service.SummaryRecord{
				Update: summaryItems,
			},
		},
	}

	if s.fileStream != nil {
		s.fileStream.StreamRecord(record)
	}
}

// sendConfig sends a config record to the server via an upsertBucket mutation
// and updates the in memory config
func (s *Sender) sendConfig(_ *service.Record, configRecord *service.ConfigRecord) {
	s.updateConfig(configRecord)
	config := s.serializeConfig()

	_, err := gql.UpsertBucket(
		s.ctx,                            // ctx
		s.graphqlClient,                  // client
		nil,                              // id
		&s.RunRecord.RunId,               // name
		emptyAsNil(&s.RunRecord.Project), // project
		emptyAsNil(&s.RunRecord.Entity),  // entity
		nil,                              // groupName
		nil,                              // description
		nil,                              // displayName
		nil,                              // notes
		nil,                              // commit
		&config,                          // config
		nil,                              // host
		nil,                              // debug
		nil,                              // program
		nil,                              // repo
		nil,                              // jobType
		nil,                              // state
		nil,                              // sweep
		nil,                              // tags []string,
		nil,                              // summaryMetrics
	)
	if err != nil {
		s.logger.Error("sender: sendConfig:", "error", err)
	}
}

// sendSystemMetrics sends a system metrics record via the file stream
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
	if s.RunRecord == nil {
		err := fmt.Errorf("sender: sendFile: RunRecord not set")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}
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

	data, err := gql.CreateRunFiles(s.ctx, s.graphqlClient, s.RunRecord.Entity, s.RunRecord.Project, s.RunRecord.RunId, []string{name})
	if err != nil {
		err = fmt.Errorf("sender: sendFile: failed to get upload urls: %s", err)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	for _, file := range data.GetCreateRunFiles().GetFiles() {
		fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), file.Name)
		task := &uploader.UploadTask{Path: fullPath, Url: *file.UploadUrl}
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
