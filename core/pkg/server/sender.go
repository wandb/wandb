package server

import (
	"context"
	"fmt"
	"io"
	"maps"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/segmentio/encoding/json"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/shared"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/artifacts"
	fs "github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/launch"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

const (
	// RFC3339Micro Modified from time.RFC3339Nano
	RFC3339Micro             = "2006-01-02T15:04:05.000000Z07:00"
	configDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	configDebouncerBurstSize = 1        // todo: audit burst size
)

type SenderOption func(*Sender)

func WithSenderFwdChannel(fwd chan *service.Record) SenderOption {
	return func(s *Sender) {
		s.fwdChan = fwd
	}
}

func WithSenderOutChannel(out chan *service.Result) SenderOption {
	return func(s *Sender) {
		s.outChan = out
	}
}

// Sender is the sender for a stream it handles the incoming messages and sends to the server
// or/and to the dispatcher/handler
type Sender struct {
	// ctx is the context for the handler
	ctx context.Context

	// cancel is the cancel function for the handler
	cancel context.CancelFunc

	// logger is the logger for the sender
	logger *observability.CoreLogger

	// settings is the settings for the sender
	settings *service.Settings

	// fwdChan is the channel for loopback messages (messages from the sender to the handler)
	fwdChan chan *service.Record

	// outChan is the channel for dispatcher messages
	outChan chan *service.Result

	// graphqlClient is the graphql client
	graphqlClient graphql.Client

	// fileStream is the file stream
	fileStream *fs.FileStream

	// filetransfer is the file uploader/downloader
	fileTransferManager *filetransfer.FileTransferManager

	// RunRecord is the run record
	// TODO: remove this and use properly updated settings
	//       + a flag indicating whether the run has started
	RunRecord *service.RunRecord

	// resumeState is the resume state
	resumeState *ResumeState

	telemetry *service.TelemetryRecord

	metricSender *MetricSender

	configDebouncer *debounce.Debouncer

	// Keep track of summary which is being updated incrementally
	summaryMap map[string]*service.SummaryItem

	// Keep track of config which is being updated incrementally
	runConfig *runconfig.RunConfig

	// Info about the (local) server we are talking to
	serverInfo *gql.ServerInfoServerInfo

	// Keep track of exit record to pass to file stream when the time comes
	exitRecord *service.Record

	syncService *SyncService

	store *Store

	jobBuilder *launch.JobBuilder

	wgFileTransfer sync.WaitGroup
}

// NewSender creates a new Sender with the given settings
func NewSender(
	ctx context.Context,
	cancel context.CancelFunc,
	logger *observability.CoreLogger,
	settings *service.Settings,
	opts ...SenderOption,
) *Sender {

	sender := &Sender{
		ctx:            ctx,
		cancel:         cancel,
		settings:       settings,
		logger:         logger,
		summaryMap:     make(map[string]*service.SummaryItem),
		runConfig:      runconfig.New(),
		telemetry:      &service.TelemetryRecord{CoreVersion: version.Version},
		wgFileTransfer: sync.WaitGroup{},
	}
	if !settings.GetXOffline().GetValue() {
		baseURL, err := url.Parse(settings.GetBaseUrl().GetValue())
		if err != nil {
			logger.CaptureFatalAndPanic("sender: failed to parse base URL", err)
		}
		backend := api.New(api.BackendOptions{
			BaseURL: baseURL,
			Logger:  logger.Logger,
			APIKey:  settings.GetApiKey().GetValue(),
		})

		graphqlHeaders := map[string]string{
			"X-WANDB-USERNAME":   settings.GetUsername().GetValue(),
			"X-WANDB-USER-EMAIL": settings.GetEmail().GetValue(),
		}
		maps.Copy(graphqlHeaders, settings.GetXExtraHttpHeaders().GetValue())

		graphqlClient := backend.NewClient(api.ClientOptions{
			RetryPolicy:     clients.CheckRetry,
			RetryMax:        int(settings.GetXGraphqlRetryMax().GetValue()),
			RetryWaitMin:    clients.SecondsToDuration(settings.GetXGraphqlRetryWaitMinSeconds().GetValue()),
			RetryWaitMax:    clients.SecondsToDuration(settings.GetXGraphqlRetryWaitMaxSeconds().GetValue()),
			NonRetryTimeout: clients.SecondsToDuration(settings.GetXGraphqlTimeoutSeconds().GetValue()),
			ExtraHeaders:    graphqlHeaders,
		})
		url := fmt.Sprintf("%s/graphql", settings.GetBaseUrl().GetValue())
		sender.graphqlClient = graphql.NewClient(url, graphqlClient)

		fileStreamHeaders := map[string]string{}
		if settings.GetXShared().GetValue() {
			fileStreamHeaders["X-WANDB-USE-ASYNC-FILESTREAM"] = "true"
		}

		fileStreamRetryClient := backend.NewClient(api.ClientOptions{
			RetryMax:        int(settings.GetXFileStreamRetryMax().GetValue()),
			RetryWaitMin:    clients.SecondsToDuration(settings.GetXFileStreamRetryWaitMinSeconds().GetValue()),
			RetryWaitMax:    clients.SecondsToDuration(settings.GetXFileStreamRetryWaitMaxSeconds().GetValue()),
			NonRetryTimeout: clients.SecondsToDuration(settings.GetXFileStreamTimeoutSeconds().GetValue()),
			ExtraHeaders:    fileStreamHeaders,
		})

		sender.fileStream = fs.NewFileStream(
			fs.WithSettings(settings),
			fs.WithLogger(logger),
			fs.WithAPIClient(fileStreamRetryClient),
			fs.WithClientId(shared.ShortID(32)),
		)

		fileTransferRetryClient := retryablehttp.NewClient()
		fileTransferRetryClient.Logger = logger
		fileTransferRetryClient.CheckRetry = clients.CheckRetry
		fileTransferRetryClient.RetryMax = int(settings.GetXFileTransferRetryMax().GetValue())
		fileTransferRetryClient.RetryWaitMin = clients.SecondsToDuration(settings.GetXFileTransferRetryWaitMinSeconds().GetValue())
		fileTransferRetryClient.RetryWaitMax = clients.SecondsToDuration(settings.GetXFileTransferRetryWaitMaxSeconds().GetValue())
		fileTransferRetryClient.HTTPClient.Timeout = clients.SecondsToDuration(settings.GetXFileTransferTimeoutSeconds().GetValue())
		fileTransferRetryClient.Backoff = clients.ExponentialBackoffWithJitter

		defaultFileTransfer := filetransfer.NewDefaultFileTransfer(
			logger,
			fileTransferRetryClient,
		)
		sender.fileTransferManager = filetransfer.NewFileTransferManager(
			filetransfer.WithLogger(logger),
			filetransfer.WithSettings(settings),
			filetransfer.WithFileTransfer(defaultFileTransfer),
			filetransfer.WithFSCChan(sender.fileStream.GetInputChan()),
		)

		sender.getServerInfo()

		if !settings.GetDisableJobCreation().GetValue() {
			sender.jobBuilder = launch.NewJobBuilder(settings, logger)
		}
	}
	sender.configDebouncer = debounce.NewDebouncer(
		configDebouncerRateLimit,
		configDebouncerBurstSize,
		logger,
	)

	for _, opt := range opts {
		opt(sender)
	}

	return sender
}

// do sending of messages to the server
func (s *Sender) Do(inChan <-chan *service.Record) {
	defer s.logger.Reraise()
	s.logger.Info("sender: started", "stream_id", s.settings.RunId)

	for record := range inChan {
		s.sendRecord(record)
		// TODO: reevaluate the logic here
		s.configDebouncer.Debounce(s.upsertConfig)
	}
	s.Close()
	s.logger.Info("sender: closed", "stream_id", s.settings.RunId)
}

func (s *Sender) Close() {
	// sender is done processing data, close our dispatch channel
	close(s.outChan)
}

func (s *Sender) GetOutboundChannel() chan *service.Result {
	return s.outChan
}

func (s *Sender) SetGraphqlClient(client graphql.Client) {
	s.graphqlClient = client
}

func (s *Sender) SendRecord(record *service.Record) {
	// this is for testing purposes only yet
	s.sendRecord(record)
}

// sendRecord sends a record
//
//gocyclo:ignore
func (s *Sender) sendRecord(record *service.Record) {
	s.logger.Debug("sender: sendRecord", "record", record, "stream_id", s.settings.RunId)
	switch x := record.RecordType.(type) {
	case *service.Record_Run:
		s.sendRun(record, x.Run)
	case *service.Record_Footer:
	case *service.Record_Header:
	case *service.Record_Final:
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
		s.sendUseArtifact(record)
	case *service.Record_Artifact:
		s.sendArtifact(record, x.Artifact)
	case *service.Record_WandbConfigParameters:
		s.sendWandbConfigParameters(record, x.WandbConfigParameters)
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
	case *service.Request_LogArtifact:
		s.sendLogArtifact(record, x.LogArtifact)
	case *service.Request_PollExit:
	case *service.Request_ServerInfo:
		s.sendServerInfo(record, x.ServerInfo)
	case *service.Request_DownloadArtifact:
		s.sendDownloadArtifact(record, x.DownloadArtifact)
	case *service.Request_Sync:
		s.sendSync(record, x.Sync)
	case *service.Request_SenderRead:
		s.sendSenderRead(record, x.SenderRead)
	case *service.Request_Cancel:
		// TODO: audit this
	case nil:
		err := fmt.Errorf("sender: sendRequest: nil RequestType")
		s.logger.CaptureFatalAndPanic("sender: sendRequest: nil RequestType", err)
	default:
		err := fmt.Errorf("sender: sendRequest: unexpected type %T", x)
		s.logger.CaptureFatalAndPanic("sender: sendRequest: unexpected type", err)
	}
}

// updateSettings updates the settings from the run record upon a run start
// with the information from the server
func (s *Sender) updateSettings() {
	if s.settings == nil || s.RunRecord == nil {
		return
	}

	if s.settings.XStartTime == nil && s.RunRecord.StartTime != nil {
		startTime := float64(s.RunRecord.StartTime.Seconds) + float64(s.RunRecord.StartTime.Nanos)/1e9
		s.settings.XStartTime = &wrapperspb.DoubleValue{Value: startTime}
	}

	// TODO: verify that this is the correct update logic
	if s.RunRecord.GetEntity() != "" {
		s.settings.Entity = &wrapperspb.StringValue{Value: s.RunRecord.Entity}
	}
	if s.RunRecord.GetProject() != "" && s.settings.Project == nil {
		s.settings.Project = &wrapperspb.StringValue{Value: s.RunRecord.Project}
	}
	if s.RunRecord.GetDisplayName() != "" && s.settings.RunName == nil {
		s.settings.RunName = &wrapperspb.StringValue{Value: s.RunRecord.DisplayName}
	}
}

// sendRun starts up all the resources for a run
func (s *Sender) sendRunStart(_ *service.RunStartRequest) {
	fsPath := fmt.Sprintf(
		"files/%s/%s/%s/file_stream",
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
	)

	fs.WithPath(fsPath)(s.fileStream)
	fs.WithOffsets(s.resumeState.GetFileStreamOffset())(s.fileStream)

	s.updateSettings()
	s.fileStream.Start()
	s.fileTransferManager.Start()
}

func (s *Sender) sendNetworkStatusRequest(_ *service.NetworkStatusRequest) {
}

func (s *Sender) sendJobFlush() {
	if s.jobBuilder == nil {
		return
	}
	s.jobBuilder.SetRunConfig(*s.runConfig)
	output := make(map[string]interface{})

	var out interface{}
	for k, v := range s.summaryMap {
		bytes := []byte(v.GetValueJson())
		err := json.Unmarshal(bytes, &out)
		if err != nil {
			s.logger.Error("sender: sendDefer: failed to unmarshal summary", "error", err)
			return
		}
		output[k] = out
	}

	artifact, err := s.jobBuilder.Build(output)
	if err != nil {
		s.logger.Error("sender: sendDefer: failed to build job artifact", "error", err)
		return
	}
	if artifact == nil {
		s.logger.Info("sender: sendDefer: no job artifact to save")
		return
	}
	saver := artifacts.NewArtifactSaver(
		s.ctx, s.graphqlClient, s.fileTransferManager, artifact, 0, "",
	)
	if _, err = saver.Save(s.fwdChan); err != nil {
		s.logger.Error("sender: sendDefer: failed to save job artifact", "error", err)
	}
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
		s.writeAndSendConfigFile()
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_OUTPUT:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_JOB:
		s.sendJobFlush()
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_DIR:
		request.State++
		s.sendRequestDefer(request)
	case service.DeferRequest_FLUSH_FP:
		s.wgFileTransfer.Wait()
		s.fileTransferManager.Close()
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
		s.syncService.Flush()
		s.respondExit(s.exitRecord)
		// cancel tells the stream to close the loopback channel
		s.cancel()
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
	s.fwdChan <- rec
}

func (s *Sender) sendTelemetry(_ *service.Record, telemetry *service.TelemetryRecord) {
	proto.Merge(s.telemetry, telemetry)
	s.updateConfigPrivate()
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

func (s *Sender) sendUseArtifact(record *service.Record) {
	if s.jobBuilder == nil {
		s.logger.Warn("sender: sendUseArtifact: job builder disabled, skipping")
		return
	}
	s.jobBuilder.HandleUseArtifactRecord(record)
}

// Applies the change record to the run configuration.
func (s *Sender) updateConfig(configRecord *service.ConfigRecord) {
	s.runConfig.ApplyChangeRecord(configRecord, func(err error) {
		s.logger.CaptureError("Error updating run config", err)
	})
}

// Inserts W&B-internal information into the run configuration.
//
// Uses the given telemetry
func (s *Sender) updateConfigPrivate() {
	metrics := []map[int]interface{}(nil)
	if s.metricSender != nil {
		metrics = s.metricSender.configMetrics
	}

	s.runConfig.AddTelemetryAndMetrics(s.telemetry, metrics)
}

// Serializes the run configuration to send to the backend.
func (s *Sender) serializeConfig(format runconfig.ConfigFormat) string {
	serializedConfig, err := s.runConfig.Serialize(format)

	if err != nil {
		err = fmt.Errorf("failed to marshal config: %s", err)
		s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
	}

	return string(serializedConfig)
}

func (s *Sender) sendRunResult(record *service.Record, runResult *service.RunUpdateResult) {
	result := &service.Result{
		ResultType: &service.Result_RunResult{
			RunResult: runResult,
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result

}

func (s *Sender) checkAndUpdateResumeState(record *service.Record) error {
	if s.graphqlClient == nil {
		return nil
	}
	// There was no resume status set, so we don't need to do anything
	if s.settings.GetResume().GetValue() == "" {
		return nil
	}

	// init resume state if it doesn't exist
	s.resumeState = NewResumeState(s.logger, s.settings.GetResume().GetValue())
	run := s.RunRecord
	// If we couldn't get the resume status, we should fail if resume is set
	data, err := gql.RunResumeStatus(s.ctx, s.graphqlClient, &run.Project, utils.NilIfZero(run.Entity), run.RunId)
	if err != nil {
		err = fmt.Errorf("failed to get run resume status: %s", err)
		s.logger.Error("sender:", "error", err)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_COMMUNICATION,
			}}
		s.sendRunResult(record, result)
		return err
	}

	if result, err := s.resumeState.Update(
		data,
		s.RunRecord,
		s.runConfig,
	); err != nil {
		s.sendRunResult(record, result)
		return err
	}

	return nil
}

func (s *Sender) sendRun(record *service.Record, run *service.RunRecord) {
	if s.graphqlClient != nil {
		// The first run record sent by the client is encoded incorrectly,
		// causing it to overwrite the entire "_wandb" config key rather than
		// just the necessary part ("_wandb/code_path"). This can overwrite
		// the config from a resumed run, so we have to do this first.
		//
		// Logically, it would make more sense to instead start with the
		// resumed config and apply updates on top of it.
		s.updateConfig(run.Config)
		proto.Merge(s.telemetry, run.Telemetry)
		s.updateConfigPrivate()

		if s.RunRecord == nil {
			var ok bool
			s.RunRecord, ok = proto.Clone(run).(*service.RunRecord)
			if !ok {
				err := fmt.Errorf("failed to clone RunRecord")
				s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
			}

			if err := s.checkAndUpdateResumeState(record); err != nil {
				s.logger.Error("sender: sendRun: failed to checkAndUpdateResumeState", "error", err)
				return
			}
		}

		config := s.serializeConfig(runconfig.FormatJson)

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
			utils.NilIfZero(run.SweepId),     // sweep
			tags,                             // tags []string,
			nil,                              // summaryMetrics
		)
		if err != nil {
			err = fmt.Errorf("failed to upsert bucket: %s", err)
			s.logger.Error("sender: sendRun:", "error", err)
			// TODO(run update): handle error communication back to the client
			fmt.Println("ERROR: failed to upsert bucket", err.Error())
			// TODO(sync): make this more robust in case of a failed UpsertBucket request.
			//  Need to inform the sync service that this ops failed.
			if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
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

		bucket := data.GetUpsertBucket().GetBucket()
		project := bucket.GetProject()
		entity := project.GetEntity()
		s.RunRecord.StorageId = bucket.GetId()
		// s.RunRecord.RunId = bucket.GetName()
		s.RunRecord.DisplayName = utils.ZeroIfNil(bucket.GetDisplayName())
		s.RunRecord.Project = project.GetName()
		s.RunRecord.Entity = entity.GetName()
		s.RunRecord.SweepId = utils.ZeroIfNil(bucket.GetSweepName())
	}

	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
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
	config := s.serializeConfig(runconfig.FormatJson)

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

func (s *Sender) writeAndSendConfigFile() {
	if s.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	config := s.serializeConfig(runconfig.FormatYaml)
	configFile := filepath.Join(s.settings.GetFilesDir().GetValue(), ConfigFileName)
	if err := os.WriteFile(configFile, []byte(config), 0644); err != nil {
		s.logger.Error("sender: writeAndSendConfigFile: failed to write config file", "error", err)
	}

	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: ConfigFileName,
						Type: service.FilesItem_WANDB,
					},
				},
			},
		},
	}
	s.fwdChan <- record
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

	outputFile := filepath.Join(s.settings.GetFilesDir().GetValue(), OutputFileName)
	// append line to file
	f, err := os.OpenFile(outputFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		s.logger.Error("sender: sendOutputRaw: failed to open output file", "error", err)
	}
	if _, err := f.WriteString(outputRaw.Line + "\n"); err != nil {
		s.logger.Error("sender: sendOutputRaw: failed to write to output file", "error", err)
	}
	defer func() {
		if err := f.Close(); err != nil {
			s.logger.Error("sender: sendOutputRaw: failed to close output file", "error", err)
		}
	}()

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
		err := fmt.Errorf("sender: sendAlert: RunRecord not set")
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
	if record == nil || s.settings.GetXSync().GetValue() {
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
	if record.Control == nil {
		record.Control = &service.Control{AlwaysSend: true}
	}

	rec := &service.Record{
		RecordType: &service.Record_Request{Request: request},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.fwdChan <- rec
}

// sendMetric sends a metrics record to the file stream,
// which will then send it to the server
func (s *Sender) sendMetric(record *service.Record, metric *service.MetricRecord) {
	if s.metricSender == nil {
		s.metricSender = NewMetricSender()
	}

	if metric.GetGlobName() != "" {
		s.logger.Warn("sender: sendMetric: glob name is not supported in the backend", "globName", metric.GetGlobName())
		return
	}

	s.encodeMetricHints(record, metric)
	s.updateConfigPrivate()
	s.sendConfig(nil, nil /*configRecord*/)
}

// sendFiles iterates over the files in the FilesRecord and sends them to
func (s *Sender) sendFiles(_ *service.Record, filesRecord *service.FilesRecord) {
	files := filesRecord.GetFiles()
	for _, file := range files {
		if strings.HasPrefix(file.GetPath(), "media") {
			file.Type = service.FilesItem_MEDIA
		}
		s.wgFileTransfer.Add(1)
		go func(file *service.FilesItem) {
			s.sendFile(file)
			s.wgFileTransfer.Done()
		}(file)
	}
}

// sendFile sends a file to the server
// TODO: improve this to handle multiple files and send them in one request
func (s *Sender) sendFile(file *service.FilesItem) {
	if s.graphqlClient == nil || s.fileTransferManager == nil {
		return
	}

	if s.RunRecord == nil {
		err := fmt.Errorf("sender: sendFile: RunRecord not set")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), file.GetPath())
	if _, err := os.Stat(fullPath); os.IsNotExist(err) {
		s.logger.Warn("sender: sendFile: file does not exist", "path", fullPath)
		return
	}

	data, err := gql.CreateRunFiles(
		s.ctx,
		s.graphqlClient,
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
		[]string{file.GetPath()},
	)
	if err != nil {
		err = fmt.Errorf("sender: sendFile: failed to get upload urls: %s", err)
		s.logger.CaptureError("sender received error", err)
		return
	}
	headers := data.GetCreateRunFiles().GetUploadHeaders()
	for _, f := range data.GetCreateRunFiles().GetFiles() {
		fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), f.Name)
		task := &filetransfer.Task{
			Type:    filetransfer.UploadTask,
			Path:    fullPath,
			Name:    f.Name,
			Url:     *f.UploadUrl,
			Headers: headers,
		}

		task.SetProgressCallback(
			func(processed, total int) {
				if processed == 0 {
					return
				}
				record := &service.Record{
					RecordType: &service.Record_Request{
						Request: &service.Request{
							RequestType: &service.Request_FileTransferInfo{
								FileTransferInfo: &service.FileTransferInfoRequest{
									Type:      service.FileTransferInfoRequest_Upload,
									Path:      fullPath,
									Size:      int64(total),
									Processed: int64(processed),
								},
							},
						},
					},
				}
				s.fwdChan <- record
			},
		)
		task.SetCompletionCallback(
			func(t *filetransfer.Task) {
				s.fileTransferManager.FileStreamCallback(t)
				fileCounts := &service.FileCounts{}
				switch file.GetType() {
				case service.FilesItem_MEDIA:
					fileCounts.MediaCount = 1
				case service.FilesItem_OTHER:
					fileCounts.OtherCount = 1
				case service.FilesItem_WANDB:
					fileCounts.WandbCount = 1
				}

				record := &service.Record{
					RecordType: &service.Record_Request{
						Request: &service.Request{
							RequestType: &service.Request_FileTransferInfo{
								FileTransferInfo: &service.FileTransferInfoRequest{
									Type:       service.FileTransferInfoRequest_Upload,
									Path:       fullPath,
									Size:       t.Size,
									Processed:  t.Size,
									FileCounts: fileCounts,
								},
							},
						},
					},
				}
				s.fwdChan <- record
			},
		)
		s.fileTransferManager.AddTask(task)
	}
}

func (s *Sender) sendArtifact(_ *service.Record, msg *service.ArtifactRecord) {
	saver := artifacts.NewArtifactSaver(
		s.ctx, s.graphqlClient, s.fileTransferManager, msg, 0, "",
	)
	artifactID, err := saver.Save(s.fwdChan)
	if err != nil {
		err = fmt.Errorf("sender: sendArtifact: failed to log artifact ID: %s; error: %s", artifactID, err)
		s.logger.Error("sender: sendArtifact:", "error", err)
		return
	}
}

func (s *Sender) sendLogArtifact(record *service.Record, msg *service.LogArtifactRequest) {
	var response service.LogArtifactResponse
	saver := artifacts.NewArtifactSaver(
		s.ctx, s.graphqlClient, s.fileTransferManager, msg.Artifact, msg.HistoryStep, msg.StagingDir,
	)
	artifactID, err := saver.Save(s.fwdChan)
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
	s.jobBuilder.HandleLogArtifactResult(&response, msg.Artifact)
	s.outChan <- result
}

func (s *Sender) sendDownloadArtifact(record *service.Record, msg *service.DownloadArtifactRequest) {
	// TODO: this should be handled by a separate service starup mechanism
	s.fileTransferManager.Start()

	var response service.DownloadArtifactResponse
	downloader := artifacts.NewArtifactDownloader(s.ctx, s.graphqlClient, s.fileTransferManager, msg.ArtifactId, msg.DownloadRoot, &msg.AllowMissingReferences)
	err := downloader.Download()
	if err != nil {
		s.logger.CaptureError("senderError: downloadArtifact: failed to download artifact: %v", err)
		response.ErrorMessage = err.Error()
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_DownloadArtifactResponse{
					DownloadArtifactResponse: &response,
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
}

func (s *Sender) sendSync(record *service.Record, request *service.SyncRequest) {

	s.syncService = NewSyncService(s.ctx,
		WithSyncServiceLogger(s.logger),
		WithSyncServiceSenderFunc(s.sendRecord),
		WithSyncServiceOverwrite(request.GetOverwrite()),
		WithSyncServiceSkip(request.GetSkip()),
		WithSyncServiceFlushCallback(func(err error) {
			var errorInfo *service.ErrorInfo
			if err != nil {
				errorInfo = &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				}
			}

			var url string
			if s.RunRecord != nil {
				baseUrl := s.settings.GetBaseUrl().GetValue()
				baseUrl = strings.Replace(baseUrl, "api.", "", 1)
				url = fmt.Sprintf("%s/%s/%s/runs/%s", baseUrl, s.RunRecord.Entity, s.RunRecord.Project, s.RunRecord.RunId)
			}
			result := &service.Result{
				ResultType: &service.Result_Response{
					Response: &service.Response{
						ResponseType: &service.Response_SyncResponse{
							SyncResponse: &service.SyncResponse{
								Url:   url,
								Error: errorInfo,
							},
						},
					},
				},
				Control: record.Control,
				Uuid:    record.Uuid,
			}
			s.outChan <- result
		}),
	)
	s.syncService.Start()

	rec := &service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_SenderRead{
					SenderRead: &service.SenderReadRequest{
						StartOffset: request.GetStartOffset(),
						FinalOffset: request.GetFinalOffset(),
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.fwdChan <- rec
}

func (s *Sender) sendSenderRead(_ *service.Record, _ *service.SenderReadRequest) {
	if s.store == nil {
		store := NewStore(s.ctx, s.settings.GetSyncFile().GetValue(), s.logger)
		err := store.Open(os.O_RDONLY)
		if err != nil {
			s.logger.CaptureError("sender: sendSenderRead: failed to create store", err)
			return
		}
		s.store = store
	}
	// TODO:
	// 1. seek to startOffset
	//
	// if err := s.store.reader.SeekRecord(request.GetStartOffset()); err != nil {
	// 	s.logger.CaptureError("sender: sendSenderRead: failed to seek record", err)
	// 	return
	// }
	// 2. read records until finalOffset
	//
	for {
		record, err := s.store.Read()
		if s.settings.GetXSync().GetValue() {
			s.syncService.SyncRecord(record, err)
		} else if record != nil {
			s.sendRecord(record)
		}
		if err == io.EOF {
			return
		}
		if err != nil {
			s.logger.CaptureError("sender: sendSenderRead: failed to read record", err)
			return
		}
	}
}

func (s *Sender) getServerInfo() {
	if s.graphqlClient == nil {
		return
	}

	data, err := gql.ServerInfo(s.ctx, s.graphqlClient)
	if err != nil {
		err = fmt.Errorf("sender: getServerInfo: failed to get server info: %s", err)
		s.logger.CaptureError("sender received error", err)
		return
	}
	s.serverInfo = data.GetServerInfo()

	s.logger.Info("sender: getServerInfo: got server info", "serverInfo", s.serverInfo)
}

// TODO: this function is for deciding which GraphQL query/mutation versions to use
// func (s *Sender) getServerVersion() string {
// 	if s.serverInfo == nil {
// 		return ""
// 	}
// 	return s.serverInfo.GetLatestLocalVersionInfo().GetVersionOnThisInstanceString()
// }

func (s *Sender) sendServerInfo(record *service.Record, _ *service.ServerInfoRequest) {

	localInfo := &service.LocalInfo{}
	if s.serverInfo != nil && s.serverInfo.GetLatestLocalVersionInfo() != nil {
		localInfo = &service.LocalInfo{
			Version:   s.serverInfo.GetLatestLocalVersionInfo().GetLatestVersionString(),
			OutOfDate: s.serverInfo.GetLatestLocalVersionInfo().GetOutOfDate(),
		}
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_ServerInfoResponse{
					ServerInfoResponse: &service.ServerInfoResponse{
						LocalInfo: localInfo,
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
}

func (s *Sender) sendWandbConfigParameters(_ *service.Record, wandbConfigParameters *service.LaunchWandbConfigParametersRecord) {
	s.jobBuilder.HandleLaunchWandbConfigParametersRecord(wandbConfigParameters)
}
