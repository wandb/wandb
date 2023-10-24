package server

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/nexus/internal/clients"
	"github.com/wandb/wandb/nexus/internal/debounce"
	"github.com/wandb/wandb/nexus/internal/gql"
	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/internal/uploader"
	"github.com/wandb/wandb/nexus/internal/version"
	"github.com/wandb/wandb/nexus/pkg/artifacts"
	fs "github.com/wandb/wandb/nexus/pkg/filestream"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
	"github.com/wandb/wandb/nexus/pkg/utils"
)

const (
	MetaFilename = "wandb-metadata.json"
	// RFC3339Micro Modified from time.RFC3339Nano
	RFC3339Micro             = "2006-01-02T15:04:05.000000Z07:00"
	configDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	configDebouncerBurstSize = 1        // todo: audit burst size
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

	// loopbackChan is the channel for loopback messages (messages from the sender to the handler)
	loopbackChan chan *service.Record

	// outChan is the channel for dispatcher messages
	outChan chan *service.Result

	// graphqlClient is the graphql client
	graphqlClient graphql.Client

	// fileStream is the file stream
	fileStream *fs.FileStream

	// uploader is the file uploader
	uploadManager *uploader.UploadManager

	// RunRecord is the run record
	RunRecord *service.RunRecord

	// resumeState is the resume state
	resumeState *ResumeState

	telemetry *service.TelemetryRecord

	ms *MetricSender

	configDebouncer *debounce.Debouncer

	// Keep track of summary which is being updated incrementally
	summaryMap map[string]*service.SummaryItem

	// Keep track of config which is being updated incrementally
	configMap map[string]interface{}

	// Keep track of exit record to pass to file stream when the time comes
	exitRecord *service.Record
}

// NewSender creates a new Sender with the given settings
func NewSender(ctx context.Context, settings *service.Settings, logger *observability.NexusLogger, loopbackChan chan *service.Record) *Sender {

	sender := &Sender{
		ctx:          ctx,
		settings:     settings,
		logger:       logger,
		summaryMap:   make(map[string]*service.SummaryItem),
		configMap:    make(map[string]interface{}),
		loopbackChan: loopbackChan,
		outChan:      make(chan *service.Result, BufferSize),
		telemetry:    &service.TelemetryRecord{CoreVersion: version.Version},
	}
	if !settings.GetXOffline().GetValue() {
		baseHeaders := map[string]string{
			"X-WANDB-USERNAME":   settings.GetUsername().GetValue(),
			"X-WANDB-USER-EMAIL": settings.GetEmail().GetValue(),
		}
		graphqlRetryClient := clients.NewRetryClient(
			clients.WithRetryClientLogger(logger),
			clients.WithRetryClientHttpAuthTransport(
				settings.GetApiKey().GetValue(),
				baseHeaders,
				settings.GetXExtraHttpHeaders().GetValue(),
			),
			clients.WithRetryClientRetryPolicy(clients.CheckRetry),
			clients.WithRetryClientRetryMax(int(settings.GetXGraphqlRetryMax().GetValue())),
			clients.WithRetryClientRetryWaitMin(time.Duration(settings.GetXGraphqlRetryWaitMinSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientRetryWaitMax(time.Duration(settings.GetXGraphqlRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientHttpTimeout(time.Duration(settings.GetXGraphqlTimeoutSeconds().GetValue()*int32(time.Second))),
		)
		url := fmt.Sprintf("%s/graphql", settings.GetBaseUrl().GetValue())
		sender.graphqlClient = graphql.NewClient(url, graphqlRetryClient.StandardClient())

		fileStreamRetryClient := clients.NewRetryClient(
			clients.WithRetryClientLogger(logger),
			clients.WithRetryClientRetryMax(int(settings.GetXFileStreamRetryMax().GetValue())),
			clients.WithRetryClientRetryWaitMin(time.Duration(settings.GetXFileStreamRetryWaitMinSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientRetryWaitMax(time.Duration(settings.GetXFileStreamRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientHttpTimeout(time.Duration(settings.GetXFileStreamTimeoutSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientHttpAuthTransport(sender.settings.GetApiKey().GetValue()),
			// TODO(nexus:beta): add jitter to DefaultBackoff scheme
			// retryClient.BackOff = fs.GetBackoffFunc()
			// TODO(nexus:beta): add custom retry function
			// retryClient.CheckRetry = fs.GetCheckRetryFunc()
		)
		sender.fileStream = fs.NewFileStream(
			fs.WithSettings(settings),
			fs.WithLogger(logger),
			fs.WithHttpClient(fileStreamRetryClient),
		)
		uploaderRetryClient := clients.NewRetryClient(
			clients.WithRetryClientLogger(logger),
			clients.WithRetryClientRetryMax(int(settings.GetXFileUploaderRetryMax().GetValue())),
			clients.WithRetryClientRetryWaitMin(time.Duration(settings.GetXFileUploaderRetryWaitMinSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientRetryWaitMax(time.Duration(settings.GetXFileUploaderRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
			clients.WithRetryClientHttpTimeout(time.Duration(settings.GetXFileUploaderTimeoutSeconds().GetValue()*int32(time.Second))),
		)
		defaultUploader := uploader.NewDefaultUploader(
			logger,
			uploaderRetryClient,
		)
		sender.uploadManager = uploader.NewUploadManager(
			uploader.WithLogger(logger),
			uploader.WithSettings(settings),
			uploader.WithUploader(defaultUploader),
		)

	}
	sender.configDebouncer = debounce.NewDebouncer(
		configDebouncerRateLimit,
		configDebouncerBurstSize,
		logger,
	)

	return sender
}

// do sending of messages to the server
func (s *Sender) do(inChan <-chan *service.Record) {
	defer s.logger.Reraise()
	s.logger.Info("sender: started", "stream_id", s.settings.RunId)

	for record := range inChan {
		s.sendRecord(record)
		s.configDebouncer.Debounce(s.upsertConfig)
	}
	s.logger.Info("sender: closed", "stream_id", s.settings.RunId)
}

func (s *Sender) Close() {
	// sender is done processing data, close our dispatch channel
	close(s.outChan)
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
	case *service.Record_Metric:
		s.sendMetric(record, x.Metric)
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
	case *service.Record_Telemetry:
		s.sendTelemetry(record, x.Telemetry)
	case *service.Record_Preempting:
		s.sendPreempting(record)
	case *service.Record_Request:
		s.sendRequest(record, x.Request)
	case *service.Record_LinkArtifact:
		s.sendLinkArtifact(record)
	case *service.Record_UseArtifact:
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
	case *service.Request_PollExit:
		s.sendPollExit(record, x.PollExit)
	case *service.Request_ServerInfo:
		s.sendServerInfo(record, x.ServerInfo)
	default:
		// TODO: handle errors
	}
}

// sendRun starts up all the resources for a run
func (s *Sender) sendRunStart(_ *service.RunStartRequest) {
	fsPath := fmt.Sprintf("%s/files/%s/%s/%s/file_stream",
		s.settings.GetBaseUrl().GetValue(), s.RunRecord.Entity, s.RunRecord.Project, s.RunRecord.RunId)

	fs.WithPath(fsPath)(s.fileStream)
	fs.WithOffsets(s.resumeState.GetFileStreamOffset())(s.fileStream)

	s.fileStream.Start()
	s.uploadManager.Start()
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
	s.sendFile(MetaFilename, uploader.WandbFile)
}

func (s *Sender) sendDefer(request *service.DeferRequest) {
	switch request.State {
	case service.DeferRequest_BEGIN:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_RUN:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_STATS:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_TB:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_SUM:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_DEBOUNCER:
		s.configDebouncer.Flush(s.upsertConfig)
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_OUTPUT:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_JOB:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_DIR:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_FP:
		s.uploadManager.Close()
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_JOIN_FP:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_FS:
		s.fileStream.Close()
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_FINAL:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_END:
		request.State++
		s.respondExit(s.exitRecord)
	default:
		err := fmt.Errorf("sender: sendDefer: unexpected state %v", request.State)
		s.logger.CaptureFatalAndPanic("sender: sendDefer: unexpected state", err)
	}
}

func (s *Sender) sendRequestDefer(request *service.DeferRequest) {
	rec := &service.Record{
		RecordType: &service.Record_Request{Request: &service.Request{
			RequestType: &service.Request_Defer{Defer: request},
		}},
		Control: &service.Control{AlwaysSend: true},
	}
	s.loopbackChan <- rec
}

func (s *Sender) sendTelemetry(_ *service.Record, telemetry *service.TelemetryRecord) {
	proto.Merge(s.telemetry, telemetry)
	s.updateConfigPrivate(s.telemetry)
	// TODO(perf): improve when debounce config is added, for now this sends all the time
	s.sendConfig(nil, nil /*configRecord*/)
}

func (s *Sender) sendPreempting(record *service.Record) {
	s.fileStream.StreamRecord(record)
}

func (s *Sender) sendLinkArtifact(record *service.Record) {
	linker := artifacts.ArtifactLinker{
		Ctx:           s.ctx,
		Logger:        s.logger,
		LinkArtifact:  record.GetLinkArtifact(),
		GraphqlClient: s.graphqlClient,
	}
	err := linker.Link()
	if err != nil {
		s.logger.CaptureFatalAndPanic("sender: sendLinkArtifact: link failure", err)
	}

	result := &service.Result{
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
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
		keyList := d.GetNestedKey()
		if keyList == nil {
			keyList = []string{d.GetKey()}
		}
		target := s.configMap
		for _, k := range keyList[:len(keyList)-1] {
			val, ok := target[k].(map[string]interface{})
			if !ok {
				val = make(map[string]interface{})
				target[k] = val
			}
			target = val
		}
		target[keyList[len(keyList)-1]] = value
	}
	for _, d := range configRecord.GetRemove() {
		delete(s.configMap, d.GetKey())
	}
}

// updateConfigPrivate updates the private part of the config map
func (s *Sender) updateConfigPrivate(telemetry *service.TelemetryRecord) {
	if _, ok := s.configMap["_wandb"]; !ok {
		s.configMap["_wandb"] = make(map[string]interface{})
	}

	switch v := s.configMap["_wandb"].(type) {
	case map[string]interface{}:
		if telemetry.GetCliVersion() != "" {
			v["cli_version"] = telemetry.CliVersion
		}
		if telemetry.GetPythonVersion() != "" {
			v["python_version"] = telemetry.PythonVersion
		}
		v["t"] = nexuslib.ProtoEncodeToDict(s.telemetry)
		if s.ms != nil {
			v["m"] = s.ms.configMetrics
		}
		// todo: add the rest of the telemetry from telemetry
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
	return string(configJson)
}

func (s *Sender) sendRun(record *service.Record, run *service.RunRecord) {

	if s.RunRecord == nil && s.graphqlClient != nil {
		var ok bool
		s.RunRecord, ok = proto.Clone(run).(*service.RunRecord)
		if !ok {
			err := fmt.Errorf("failed to clone RunRecord")
			s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
		}

		if err := s.checkAndUpdateResumeState(record, s.RunRecord); err != nil {
			s.logger.Error("sender: sendRun: failed to checkAndUpdateResumeState", "error", err)
			return
		}
	}

	if s.graphqlClient != nil {

		s.updateConfig(run.Config)
		proto.Merge(s.telemetry, run.Telemetry)
		s.updateConfigPrivate(run.Telemetry)
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
		// start a new context with an additional argument from the parent context
		// this is used to pass the retry function to the graphql client
		ctx := context.WithValue(s.ctx, clients.CtxRetryPolicyKey, clients.UpsertBucketRetryPolicy)
		data, err := gql.UpsertBucket(
			ctx,                              // ctx
			s.graphqlClient,                  // client
			nil,                              // id
			&run.RunId,                       // name
			utils.NilIfZero(run.Project),     // project
			utils.NilIfZero(run.Entity),      // entity
			utils.NilIfZero(run.RunGroup),    // groupName
			nil,                              // description
			utils.NilIfZero(run.DisplayName), // displayName
			utils.NilIfZero(run.Notes),       // notes
			utils.NilIfZero(commit),          // commit
			&config,                          // config
			utils.NilIfZero(run.Host),        // host
			nil,                              // debug
			utils.NilIfZero(program),         // program
			utils.NilIfZero(repo),            // repo
			utils.NilIfZero(run.JobType),     // jobType
			nil,                              // state
			nil,                              // sweep
			tags,                             // tags []string,
			nil,                              // summaryMetrics
		)
		if err != nil {
			err = fmt.Errorf("failed to upsert bucket: %s", err)
			s.logger.Error("sender: sendRun:", "error", err)
			if record.Control.ReqResp || record.Control.MailboxSlot != "" {
				result := &service.Result{
					ResultType: &service.Result_RunResult{
						RunResult: &service.RunUpdateResult{
							Error: &service.ErrorInfo{
								Message: err.Error(),
								Code:    service.ErrorInfo_COMMUNICATION,
							},
						},
					},
					Control: record.Control,
					Uuid:    record.Uuid,
				}
				s.outChan <- result
			}
			return
		}

		s.RunRecord.DisplayName = *data.UpsertBucket.Bucket.DisplayName
		s.RunRecord.Project = data.UpsertBucket.Bucket.Project.Name
		s.RunRecord.Entity = data.UpsertBucket.Bucket.Project.Entity.Name
	}

	if record.Control.ReqResp || record.Control.MailboxSlot != "" {
		runResult := s.RunRecord
		if runResult == nil {
			runResult = run
		}
		result := &service.Result{
			ResultType: &service.Result_RunResult{
				RunResult: &service.RunUpdateResult{Run: runResult},
			},
			Control: record.Control,
			Uuid:    record.Uuid,
		}
		s.outChan <- result
	}
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(record *service.Record, _ *service.HistoryRecord) {
	s.fileStream.StreamRecord(record)
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

	s.fileStream.StreamRecord(record)
}

func (s *Sender) upsertConfig() {
	if s.graphqlClient == nil {
		return
	}

	config := s.serializeConfig()
	ctx := context.WithValue(s.ctx, clients.CtxRetryPolicyKey, clients.UpsertBucketRetryPolicy)
	_, err := gql.UpsertBucket(
		ctx,                                  // ctx
		s.graphqlClient,                      // client
		nil,                                  // id
		&s.RunRecord.RunId,                   // name
		utils.NilIfZero(s.RunRecord.Project), // project
		utils.NilIfZero(s.RunRecord.Entity),  // entity
		nil,                                  // groupName
		nil,                                  // description
		nil,                                  // displayName
		nil,                                  // notes
		nil,                                  // commit
		&config,                              // config
		nil,                                  // host
		nil,                                  // debug
		nil,                                  // program
		nil,                                  // repo
		nil,                                  // jobType
		nil,                                  // state
		nil,                                  // sweep
		nil,                                  // tags []string,
		nil,                                  // summaryMetrics
	)
	if err != nil {
		s.logger.Error("sender: sendConfig:", "error", err)
	}
}

// sendConfig sends a config record to the server via an upsertBucket mutation
// and updates the in memory config
func (s *Sender) sendConfig(_ *service.Record, configRecord *service.ConfigRecord) {
	if configRecord != nil {
		s.updateConfig(configRecord)
	}
	s.configDebouncer.SetNeedsDebounce()
}

// sendSystemMetrics sends a system metrics record via the file stream
func (s *Sender) sendSystemMetrics(record *service.Record, _ *service.StatsRecord) {
	s.fileStream.StreamRecord(record)
}

func (s *Sender) sendOutputRaw(record *service.Record, _ *service.OutputRawRecord) {
	// TODO: match logic handling of lines to the one in the python version
	// - handle carriage returns (for tqdm-like progress bars)
	// - handle caching multiple (non-new lines) and sending them in one chunk
	// - handle lines longer than ~60_000 characters

	// copy the record to avoid mutating the original
	recordCopy := proto.Clone(record).(*service.Record)
	outputRaw := recordCopy.GetOutputRaw()

	// ignore empty "new lines"
	if outputRaw.Line == "\n" {
		return
	}
	// generate compatible timestamp to python iso-format (microseconds without Z)
	t := strings.TrimSuffix(time.Now().UTC().Format(RFC3339Micro), "Z")
	outputRaw.Line = fmt.Sprintf("%s %s", t, outputRaw.Line)
	if outputRaw.OutputType == service.OutputRawRecord_STDERR {
		outputRaw.Line = fmt.Sprintf("ERROR %s", outputRaw.Line)
	}

	s.fileStream.StreamRecord(recordCopy)
}

func (s *Sender) sendAlert(_ *service.Record, alert *service.AlertRecord) {
	if s.graphqlClient == nil {
		return
	}

	if s.RunRecord == nil {
		err := fmt.Errorf("sender: sendFile: RunRecord not set")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}
	// TODO: handle invalid alert levels
	severity := gql.AlertSeverity(alert.Level)

	data, err := gql.NotifyScriptableRunAlert(
		s.ctx,
		s.graphqlClient,
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
		alert.Title,
		alert.Text,
		&severity,
		&alert.WaitDuration,
	)
	if err != nil {
		err = fmt.Errorf("sender: sendAlert: failed to notify scriptable run alert: %s", err)
		s.logger.CaptureError("sender received error", err)
	} else {
		s.logger.Info("sender: sendAlert: notified scriptable run alert", "data", data)
	}

}

// respondExit called from the end of the defer state machine
func (s *Sender) respondExit(record *service.Record) {
	if record == nil {
		return
	}
	if record.Control.ReqResp || record.Control.MailboxSlot != "" {
		result := &service.Result{
			ResultType: &service.Result_ExitResult{ExitResult: &service.RunExitResult{}},
			Control:    record.Control,
			Uuid:       record.Uuid,
		}
		s.outChan <- result
	}
}

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(record *service.Record, _ *service.RunExitRecord) {
	// response is done by respondExit() and called when defer state machine is complete
	s.exitRecord = record

	s.fileStream.StreamRecord(record)

	// send a defer request to the handler to indicate that the user requested to finish the stream
	// and the defer state machine can kick in triggering the shutdown process
	request := &service.Request{RequestType: &service.Request_Defer{
		Defer: &service.DeferRequest{State: service.DeferRequest_BEGIN}},
	}
	rec := &service.Record{
		RecordType: &service.Record_Request{Request: request},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.loopbackChan <- rec
}

// sendMetric sends a metrics record to the file stream,
// which will then send it to the server
func (s *Sender) sendMetric(record *service.Record, metric *service.MetricRecord) {
	if s.ms == nil {
		s.ms = NewMetricSender()
	}

	if metric.GetGlobName() != "" {
		s.logger.Warn("sender: sendMetric: glob name is not supported in the backend", "globName", metric.GetGlobName())
		return
	}

	s.encodeMetricHints(record, metric)
	s.updateConfigPrivate(nil /*telemetry*/)
	s.sendConfig(nil, nil /*configRecord*/)
}

// sendFiles iterates over the files in the FilesRecord and sends them to
func (s *Sender) sendFiles(_ *service.Record, filesRecord *service.FilesRecord) {
	files := filesRecord.GetFiles()
	for _, file := range files {
		if strings.HasPrefix(file.GetPath(), "media") {
			s.sendFile(file.GetPath(), uploader.MediaFile)
		} else {
			s.sendFile(file.GetPath(), uploader.OtherFile)
		}
	}
}

// sendFile sends a file to the server
func (s *Sender) sendFile(name string, fileType uploader.FileType) {
	if s.graphqlClient == nil || s.uploadManager == nil {
		return
	}

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
		task := &uploader.UploadTask{Path: fullPath, Url: *file.UploadUrl, FileType: fileType}
		s.uploadManager.AddTask(task)
	}
}

func (s *Sender) sendLogArtifact(record *service.Record, msg *service.LogArtifactRequest) {
	var response service.LogArtifactResponse
	saver := artifacts.NewArtifactSaver(s.ctx, s.graphqlClient, s.uploadManager, msg.Artifact, msg.HistoryStep)
	artifactID, err := saver.Save()
	if err != nil {
		response.ErrorMessage = err.Error()
	} else {
		response.ArtifactId = artifactID
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_LogArtifactResponse{
					LogArtifactResponse: &response,
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
}

func (s *Sender) sendPollExit(record *service.Record, _ *service.PollExitRequest) {
	fileCounts := s.uploadManager.GetFileCounts()

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_PollExitResponse{
					PollExitResponse: &service.PollExitResponse{
						FileCounts: fileCounts,
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
}

func (s *Sender) sendServerInfo(record *service.Record, _ *service.ServerInfoRequest) {
	if s.graphqlClient == nil {
		return
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_ServerInfoResponse{}, // todo: fill in
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
}
