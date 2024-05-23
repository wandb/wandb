package server

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/debounce"
	fs "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runresume"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/artifacts"
	"github.com/wandb/wandb/core/pkg/launch"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

const (
	configDebouncerRateLimit  = 1 / 30.0 // todo: audit rate limit
	configDebouncerBurstSize  = 1        // todo: audit burst size
	summaryDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	summaryDebouncerBurstSize = 1        // todo: audit burst size
)

type SenderParams struct {
	Logger              *observability.CoreLogger
	Settings            *service.Settings
	Backend             *api.Backend
	FileStream          fs.FileStream
	FileTransferManager filetransfer.FileTransferManager
	FileWatcher         watcher.Watcher
	RunfilesUploader    runfiles.Uploader
	GraphqlClient       graphql.Client
	Peeker              *observability.Peeker
	RunSummary          *runsummary.RunSummary
	Mailbox             *mailbox.Mailbox
	OutChan             chan *service.Result
	FwdChan             chan *service.Record
	OutputFileName      string
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
	fileStream fs.FileStream

	// fileTransferManager is the file uploader/downloader
	fileTransferManager filetransfer.FileTransferManager

	// fileWatcher notifies when files in the file system are changed
	fileWatcher watcher.Watcher

	// runfilesUploader manages uploading a run's files
	runfilesUploader runfiles.Uploader

	// RunRecord is the run record
	// TODO: remove this and use properly updated settings
	//       + a flag indicating whether the run has started
	RunRecord *service.RunRecord

	// resumeState is the resume state
	resumeState *runresume.State

	// telemetry record internal implementation of telemetry
	telemetry *service.TelemetryRecord

	// metricSender is a service for managing metrics
	metricSender *MetricSender

	// configDebouncer is the debouncer for config updates
	configDebouncer *debounce.Debouncer

	// summaryDebouncer is the debouncer for summary updates
	summaryDebouncer *debounce.Debouncer

	// runSummary is the full summary for the run
	runSummary *runsummary.RunSummary

	// Keep track of config which is being updated incrementally
	runConfig *runconfig.RunConfig

	// Info about the (local) server we are talking to
	serverInfo *gql.ServerInfoServerInfo

	// Keep track of exit record to pass to file stream when the time comes
	exitRecord *service.Record

	// syncService is the sync service syncing offline runs
	syncService *SyncService

	// store is the store where the transaction log is stored
	store *Store

	// jobBuilder is the job builder for creating jobs from the run
	// that allow users to re-run the run with different configurations
	jobBuilder *launch.JobBuilder

	// wgFileTransfer is a wait group for file transfers
	wgFileTransfer sync.WaitGroup

	// networkPeeker is a helper for peeking into network responses
	networkPeeker *observability.Peeker

	// mailbox is used to store cancel functions for each mailbox slot
	mailbox *mailbox.Mailbox

	// filename to write console output to
	outputFileName string
}

// NewSender creates a new Sender with the given settings
func NewSender(
	ctx context.Context,
	cancel context.CancelFunc,
	params SenderParams,
) *Sender {

	s := &Sender{
		ctx:                 ctx,
		cancel:              cancel,
		runConfig:           runconfig.New(),
		telemetry:           &service.TelemetryRecord{CoreVersion: version.Version},
		wgFileTransfer:      sync.WaitGroup{},
		logger:              params.Logger,
		settings:            params.Settings,
		fileStream:          params.FileStream,
		fileTransferManager: params.FileTransferManager,
		fileWatcher:         params.FileWatcher,
		runfilesUploader:    params.RunfilesUploader,
		networkPeeker:       params.Peeker,
		graphqlClient:       params.GraphqlClient,
		mailbox:             params.Mailbox,
		runSummary:          params.RunSummary,
		outChan:             params.OutChan,
		fwdChan:             params.FwdChan,
		configDebouncer: debounce.NewDebouncer(
			configDebouncerRateLimit,
			configDebouncerBurstSize,
			params.Logger,
		),
		summaryDebouncer: debounce.NewDebouncer(
			summaryDebouncerRateLimit,
			summaryDebouncerBurstSize,
			params.Logger,
		),
		outputFileName: params.OutputFileName,
	}

	backendOrNil := params.Backend
	if !s.settings.GetXOffline().GetValue() && backendOrNil != nil && !s.settings.GetDisableJobCreation().GetValue() {
		s.jobBuilder = launch.NewJobBuilder(s.settings, s.logger, false)
	}

	return s
}

// do sending of messages to the server
func (s *Sender) Do(inChan <-chan *service.Record) {
	defer s.logger.Reraise()
	s.logger.Info("sender: started", "stream_id", s.settings.RunId)

	for record := range inChan {
		s.logger.Debug(
			"sender: processing record",
			"record", record.RecordType,
			"stream_id", s.settings.RunId,
		)
		s.sendRecord(record)
		// TODO: reevaluate the logic here
		s.configDebouncer.Debounce(s.upsertConfig)
		s.summaryDebouncer.Debounce(s.streamSummary)
	}
	s.Close()
	s.logger.Info("sender: closed", "stream_id", s.settings.RunId)
}

func (s *Sender) Close() {
	// sender is done processing data, close our dispatch channel
	close(s.outChan)
}

func (s *Sender) respond(record *service.Record, response any) {
	if record == nil {
		s.logger.Error("sender: respond: nil record")
		return
	}

	switch x := response.(type) {
	case *service.Response:
		s.respondResponse(record, x)
	case *service.RunExitResult:
		s.respondExit(record, x)
	case *service.RunUpdateResult:
		s.respondRunUpdate(record, x)
	case nil:
		err := fmt.Errorf("sender: respond: nil response")
		s.logger.CaptureFatalAndPanic("sender: respond: nil response", err)
	default:
		err := fmt.Errorf("sender: respond: unexpected type %T", x)
		s.logger.CaptureFatalAndPanic("sender: respond: unexpected type", err)
	}
}

func (s *Sender) respondRunUpdate(record *service.Record, run *service.RunUpdateResult) {
	result := &service.Result{
		ResultType: &service.Result_RunResult{RunResult: run},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.outChan <- result
}

// respondResponse responds to a response record
func (s *Sender) respondResponse(record *service.Record, response *service.Response) {
	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.outChan <- result
}

// respondExit responds to an exit record
func (s *Sender) respondExit(record *service.Record, exit *service.RunExitResult) {
	if !s.exitRecord.Control.ReqResp && s.exitRecord.Control.MailboxSlot == "" {
		return
	}
	result := &service.Result{
		ResultType: &service.Result_ExitResult{ExitResult: exit},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.outChan <- result
}

// fwdRecord forwards a record to the next component
// usually the handler
func (s *Sender) fwdRecord(record *service.Record) {
	if record == nil {
		return
	}
	s.fwdChan <- record
}

func (s *Sender) SendRecord(record *service.Record) {
	// this is for testing purposes only yet
	s.sendRecord(record)
}

// sendRecord sends a record
//
//gocyclo:ignore
func (s *Sender) sendRecord(record *service.Record) {
	switch x := record.RecordType.(type) {
	case *service.Record_Header:
		// no-op
	case *service.Record_Footer:
		// no-op
	case *service.Record_Final:
		// no-op
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
		s.sendHistory(x.History)
	case *service.Record_Summary:
		s.sendSummary(record, x.Summary)
	case *service.Record_Config:
		s.sendConfig(record, x.Config)
	case *service.Record_Stats:
		s.sendSystemMetrics(x.Stats)
	case *service.Record_OutputRaw:
		s.sendOutputRaw(record, x.OutputRaw)
	case *service.Record_Output:
		s.sendOutput(record, x.Output)
	case *service.Record_Telemetry:
		s.sendTelemetry(record, x.Telemetry)
	case *service.Record_Preempting:
		s.sendPreempting(x.Preempting)
	case *service.Record_Request:
		s.sendRequest(record, x.Request)
	case *service.Record_LinkArtifact:
		s.sendLinkArtifact(record)
	case *service.Record_UseArtifact:
		s.sendUseArtifact(record)
	case *service.Record_Artifact:
		s.sendArtifact(record, x.Artifact)
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
		s.sendRequestRunStart(x.RunStart)
	case *service.Request_NetworkStatus:
		s.sendRequestNetworkStatus(record, x.NetworkStatus)
	case *service.Request_Defer:
		s.sendRequestDefer(x.Defer)
	case *service.Request_LogArtifact:
		s.sendRequestLogArtifact(record, x.LogArtifact)
	case *service.Request_ServerInfo:
		s.sendRequestServerInfo(record, x.ServerInfo)
	case *service.Request_DownloadArtifact:
		s.sendRequestDownloadArtifact(record, x.DownloadArtifact)
	case *service.Request_Sync:
		s.sendRequestSync(record, x.Sync)
	case *service.Request_SenderRead:
		s.sendRequestSenderRead(record, x.SenderRead)
	case *service.Request_StopStatus:
		s.sendRequestStopStatus(record, x.StopStatus)
	case *service.Request_JobInput:
		s.sendRequestJobInput(x.JobInput)
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
func (s *Sender) sendRequestRunStart(_ *service.RunStartRequest) {
	s.updateSettings()

	if s.fileStream != nil {
		s.fileStream.Start(
			s.RunRecord.GetEntity(),
			s.RunRecord.GetProject(),
			s.RunRecord.GetRunId(),
			s.resumeState.GetFileStreamOffset(),
		)
	}

	if s.fileTransferManager != nil {
		s.fileTransferManager.Start()
	}
}

func (s *Sender) sendRequestNetworkStatus(
	record *service.Record,
	_ *service.NetworkStatusRequest,
) {
	// in case of network peeker is not set, we don't need to do anything
	if s.networkPeeker == nil {
		return
	}

	// send the network status response if there is any
	if response := s.networkPeeker.Read(); len(response) > 0 {
		s.respond(record,
			&service.Response{
				ResponseType: &service.Response_NetworkStatusResponse{
					NetworkStatusResponse: &service.NetworkStatusResponse{
						NetworkResponses: response,
					},
				},
			},
		)
	}
}

func (s *Sender) sendJobFlush() {
	if s.jobBuilder == nil {
		return
	}
	s.jobBuilder.SetRunConfig(*s.runConfig)

	output, err := s.runSummary.CloneTree()
	if err != nil {
		s.logger.Error("sender: sendJobFlush: failed to copy run summary", "error", err)
		return
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
		s.ctx, s.logger, s.graphqlClient, s.fileTransferManager, artifact, 0, "",
	)
	if _, err = saver.Save(s.fwdChan); err != nil {
		s.logger.Error("sender: sendDefer: failed to save job artifact", "error", err)
	}
}

func (s *Sender) sendRequestDefer(request *service.DeferRequest) {
	switch request.State {
	case service.DeferRequest_BEGIN:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_RUN:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_STATS:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_TB:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_SUM:
		s.summaryDebouncer.Flush(s.streamSummary)
		s.uploadSummaryFile()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_DEBOUNCER:
		s.configDebouncer.SetNeedsDebounce()
		s.configDebouncer.Flush(s.upsertConfig)
		s.uploadConfigFile()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_OUTPUT:
		s.uploadOutputFile()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_JOB:
		s.sendJobFlush()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_DIR:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_FP:
		// Order matters: we must stop watching files first, since that pushes
		// updates to the runfiles uploader. The uploader creates file upload
		// tasks, so it must be flushed before we close the file transfer
		// manager.
		s.fileWatcher.Finish()
		s.wgFileTransfer.Wait()
		if s.fileTransferManager != nil {
			s.runfilesUploader.Finish()
			s.fileTransferManager.Close()
		}
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_JOIN_FP:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_FS:
		if s.fileStream != nil {
			s.fileStream.Close()
		}
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_FINAL:
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_END:
		request.State++
		s.syncService.Flush()
		if !s.settings.GetXSync().GetValue() {
			// if sync is enabled, we don't need to do this
			// since exit is already stored in the transaction log
			s.respond(s.exitRecord, &service.RunExitResult{})
		}
		// cancel tells the stream to close the loopback and input channels
		s.cancel()
	default:
		err := fmt.Errorf("sender: sendDefer: unexpected state %v", request.State)
		s.logger.CaptureFatalAndPanic("sender: sendDefer: unexpected state", err)
	}
}

func (s *Sender) fwdRequestDefer(request *service.DeferRequest) {
	record := &service.Record{
		RecordType: &service.Record_Request{Request: &service.Request{
			RequestType: &service.Request_Defer{Defer: request},
		}},
		Control: &service.Control{AlwaysSend: true},
	}
	s.fwdRecord(record)
}

func (s *Sender) sendTelemetry(_ *service.Record, telemetry *service.TelemetryRecord) {
	proto.Merge(s.telemetry, telemetry)
	s.updateConfigPrivate()
	// TODO(perf): improve when debounce config is added, for now this sends all the time
	s.configDebouncer.SetNeedsDebounce()
}

func (s *Sender) sendPreempting(record *service.RunPreemptingRecord) {
	if s.fileStream == nil {
		return
	}

	s.fileStream.StreamUpdate(&fs.PreemptingUpdate{Record: record})
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

	// why is this here?
	s.respond(record, &service.Response{})
}

func (s *Sender) sendUseArtifact(record *service.Record) {
	if s.jobBuilder == nil {
		s.logger.Warn("sender: sendUseArtifact: job builder disabled, skipping")
		return
	}
	s.jobBuilder.HandleUseArtifactRecord(record)
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
func (s *Sender) serializeConfig(format runconfig.Format) (string, error) {
	serializedConfig, err := s.runConfig.Serialize(format)

	if err != nil {
		err = fmt.Errorf("failed to marshal config: %s", err)
		s.logger.Error("sender: serializeConfig", "error", err)
		return "", err
	}

	return string(serializedConfig), nil
}

func (s *Sender) checkAndUpdateResumeState(record *service.Record) error {
	if s.graphqlClient == nil {
		return nil
	}
	resume := runresume.ResumeMode(s.settings.GetResume().GetValue())

	// There was no resume status set, so we don't need to do anything
	if resume == runresume.None {
		return nil
	}

	// init resume state if it doesn't exist
	s.resumeState = runresume.NewResumeState(s.logger, resume)
	run := s.RunRecord
	// If we couldn't get the resume status, we should fail if resume is set
	data, err := gql.RunResumeStatus(s.ctx, s.graphqlClient, &run.Project, utils.NilIfZero(run.Entity), run.RunId)
	if err != nil {
		err = fmt.Errorf("failed to get run resume status: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState", "error", err)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_COMMUNICATION,
			}}
		s.respond(record, result)
		return err
	}

	if result, err := s.resumeState.Update(
		data,
		s.RunRecord,
		s.runConfig,
	); err != nil {
		s.respond(record, result)
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
		s.runConfig.ApplyChangeRecord(run.Config,
			func(err error) {
				s.logger.CaptureError("Error updating run config", err)
			})

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
				s.logger.Error(
					"sender: sendRun: failed to checkAndUpdateResumeState",
					"error", err)
				return
			}
		}

		config, _ := s.serializeConfig(runconfig.FormatJson)

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

		// if the record has a mailbox slot, create a new cancelable context
		// and store the cancel function in the message registry so that
		// the context can be canceled if requested by the client
		mailboxSlot := record.GetControl().GetMailboxSlot()
		if mailboxSlot != "" {
			// if this times out, we cancel the global context
			// as there is no need to proceed with the run
			ctx = s.mailbox.Add(ctx, s.cancel, mailboxSlot)
		} else {
			// this should never happen
			s.logger.CaptureError("sender: sendRun: no mailbox slot", nil)
		}

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
				s.respond(record,
					&service.RunUpdateResult{
						Error: &service.ErrorInfo{
							Message: err.Error(),
							Code:    service.ErrorInfo_COMMUNICATION,
						},
					},
				)
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
		s.respond(record,
			&service.RunUpdateResult{
				Run: runResult,
			})
	}
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(record *service.HistoryRecord) {
	if s.fileStream == nil {
		return
	}

	s.fileStream.StreamUpdate(&fs.HistoryUpdate{Record: record})
}

func (s *Sender) streamSummary() {
	if s.fileStream == nil {
		return
	}

	update, err := s.runSummary.Flatten()
	if err != nil {
		s.logger.CaptureError("Error flattening run summary", err)
		return
	}

	s.fileStream.StreamUpdate(&fs.SummaryUpdate{
		Record: &service.SummaryRecord{Update: update},
	})
}

func (s *Sender) sendSummary(_ *service.Record, summary *service.SummaryRecord) {

	// TODO(network): buffer summary sending for network efficiency until we can send only updates
	s.runSummary.ApplyChangeRecord(
		summary,
		func(err error) {
			s.logger.CaptureError("Error updating run summary", err)
		},
	)

	s.summaryDebouncer.SetNeedsDebounce()
}

func (s *Sender) upsertConfig() {
	if s.graphqlClient == nil {
		return
	}
	if s.RunRecord == nil {
		s.logger.Error("sender: upsertConfig: RunRecord is nil")
		return
	}

	config, err := s.serializeConfig(runconfig.FormatJson)
	if err != nil {
		s.logger.Error("sender: upsertConfig: failed to serialize config", "error", err)
		return
	}
	if config == "" {
		return
	}

	ctx := context.WithValue(s.ctx, clients.CtxRetryPolicyKey, clients.UpsertBucketRetryPolicy)
	_, err = gql.UpsertBucket(
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

func (s *Sender) uploadSummaryFile() {
	if s.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	summary, err := s.runSummary.Serialize()
	if err != nil {
		s.logger.Error("sender: uploadSummaryFile: failed to serialize summary", "error", err)
		return
	}
	summaryFile := filepath.Join(s.settings.GetFilesDir().GetValue(), SummaryFileName)
	if err := os.WriteFile(summaryFile, summary, 0644); err != nil {
		s.logger.Error("sender: uploadSummaryFile: failed to write summary file", "error", err)
		return
	}

	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: SummaryFileName,
						Type: service.FilesItem_WANDB,
					},
				},
			},
		},
	}
	s.fwdRecord(record)
}

func (s *Sender) uploadConfigFile() {
	if s.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	config, err := s.serializeConfig(runconfig.FormatYaml)
	if err != nil {
		s.logger.Error("sender: writeAndSendConfigFile: failed to serialize config", "error", err)
		return
	}
	configFile := filepath.Join(s.settings.GetFilesDir().GetValue(), ConfigFileName)
	if err := os.WriteFile(configFile, []byte(config), 0644); err != nil {
		s.logger.Error("sender: writeAndSendConfigFile: failed to write config file", "error", err)
		return
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
	s.fwdRecord(record)
}

// sendConfig sends a config record to the server via an upsertBucket mutation
// and updates the in memory config
func (s *Sender) sendConfig(_ *service.Record, configRecord *service.ConfigRecord) {
	if configRecord != nil {
		s.runConfig.ApplyChangeRecord(configRecord,
			func(err error) {
				s.logger.CaptureError("Error updating run config", err)
			})
	}
	s.configDebouncer.SetNeedsDebounce()
}

// sendSystemMetrics sends a system metrics record via the file stream
func (s *Sender) sendSystemMetrics(record *service.StatsRecord) {
	if s.fileStream == nil {
		return
	}

	s.fileStream.StreamUpdate(&fs.StatsUpdate{Record: record})
}

func (s *Sender) sendOutput(_ *service.Record, _ *service.OutputRecord) {
	// TODO: implement me
}

func writeOutputToFile(file, line string) error {
	// append line to file
	f, err := os.OpenFile(file, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	_, err = fmt.Fprintln(f, line)
	return err
}

func (s *Sender) uploadOutputFile() {
	// In the end of a run, we upload the output file to the server
	// This is a bit of a duplication, as we send the same content through the
	// filestream
	// Ideally, the output content from the filestream would be converted
	// to a file on the server side, but for now we do it here as well

	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: s.outputFileName,
						Type: service.FilesItem_WANDB,
					},
				},
			},
		},
	}
	s.fwdRecord(record)
}

func (s *Sender) sendOutputRaw(_ *service.Record, outputRaw *service.OutputRawRecord) {
	// TODO: move this to filestream!
	// TODO: match logic handling of lines to the one in the python version
	// - handle carriage returns (for tqdm-like progress bars)
	// - handle caching multiple (non-new lines) and sending them in one chunk
	// - handle lines longer than ~60_000 characters

	// ignore empty "new lines"
	if outputRaw.Line == "\n" {
		return
	}

	if s.fileStream != nil {
		s.fileStream.StreamUpdate(&fs.LogsUpdate{Record: outputRaw})
	}

	// create a folder for the output file if it doesn't exist
	fullFilePath := filepath.Join(s.settings.GetFilesDir().GetValue(), s.outputFileName)
	logPath := filepath.Dir(fullFilePath)
	// check if the directory exists
	if _, err := os.Stat(logPath); os.IsNotExist(err) {
		// create the directory
		if err := os.MkdirAll(logPath, 0755); err != nil {
			s.logger.Error("sender: sendOutput: failed to create output file directory", "error", err)
			return
		}
	}

	// append line to file
	if err := writeOutputToFile(fullFilePath, outputRaw.Line); err != nil {
		s.logger.Error("sender: sendOutput: failed to write to output file", "error", err)
	}
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

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(record *service.Record, exitRecord *service.RunExitRecord) {
	// response is done by respond() and called when defer state machine is complete
	s.exitRecord = record

	if s.fileStream != nil {
		s.fileStream.StreamUpdate(&fs.ExitUpdate{Record: exitRecord})
	}

	// send a defer request to the handler to indicate that the user requested to finish the stream
	// and the defer state machine can kick in triggering the shutdown process
	request := &service.Request{RequestType: &service.Request_Defer{
		Defer: &service.DeferRequest{State: service.DeferRequest_BEGIN}},
	}
	if record.Control == nil {
		record.Control = &service.Control{AlwaysSend: true}
	}

	s.fwdRecord(
		&service.Record{
			RecordType: &service.Record_Request{
				Request: request,
			},
			Uuid:    record.Uuid,
			Control: record.Control,
		},
	)
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
	s.configDebouncer.SetNeedsDebounce()
}

// sendFiles uploads files according to a FilesRecord
func (s *Sender) sendFiles(_ *service.Record, filesRecord *service.FilesRecord) {
	if s.runfilesUploader == nil {
		s.logger.CaptureWarn(
			"sender: tried to sendFiles, but runfiles uploader is nil",
		)
		return
	}

	s.runfilesUploader.Process(filesRecord)
}

func (s *Sender) sendArtifact(_ *service.Record, msg *service.ArtifactRecord) {
	saver := artifacts.NewArtifactSaver(
		s.ctx, s.logger, s.graphqlClient, s.fileTransferManager, msg, 0, "",
	)
	artifactID, err := saver.Save(s.fwdChan)
	if err != nil {
		err = fmt.Errorf("sender: sendArtifact: failed to log artifact ID: %s; error: %s", artifactID, err)
		s.logger.Error("sender: sendArtifact:", "error", err)
		return
	}
}

func (s *Sender) sendRequestLogArtifact(record *service.Record, msg *service.LogArtifactRequest) {
	var response service.LogArtifactResponse
	saver := artifacts.NewArtifactSaver(
		s.ctx, s.logger, s.graphqlClient, s.fileTransferManager, msg.Artifact, msg.HistoryStep, msg.StagingDir,
	)
	artifactID, err := saver.Save(s.fwdChan)
	if err != nil {
		response.ErrorMessage = err.Error()
	} else {
		response.ArtifactId = artifactID
	}

	s.jobBuilder.HandleLogArtifactResult(&response, msg.Artifact)
	s.respond(record,
		&service.Response{
			ResponseType: &service.Response_LogArtifactResponse{
				LogArtifactResponse: &response,
			},
		})
}

func (s *Sender) sendRequestDownloadArtifact(record *service.Record, msg *service.DownloadArtifactRequest) {
	// TODO: this should be handled by a separate service startup mechanism
	s.fileTransferManager.Start()

	var response service.DownloadArtifactResponse
	downloader := artifacts.NewArtifactDownloader(
		s.ctx, s.graphqlClient, s.fileTransferManager, msg.ArtifactId, msg.DownloadRoot,
		msg.AllowMissingReferences, msg.SkipCache, msg.PathPrefix)
	err := downloader.Download()
	if err != nil {
		s.logger.CaptureError("senderError: downloadArtifact: failed to download artifact: %v", err)
		response.ErrorMessage = err.Error()
	}

	s.respond(record,
		&service.Response{
			ResponseType: &service.Response_DownloadArtifactResponse{
				DownloadArtifactResponse: &response,
			},
		})
}

func (s *Sender) sendRequestSync(record *service.Record, request *service.SyncRequest) {

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
			s.respond(record,
				&service.Response{
					ResponseType: &service.Response_SyncResponse{
						SyncResponse: &service.SyncResponse{
							Url:   url,
							Error: errorInfo,
						},
					},
				},
			)
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
	s.fwdRecord(rec)
}

func (s *Sender) sendRequestStopStatus(record *service.Record, _ *service.StopStatusRequest) {

	// TODO: unify everywhere to use settings
	entity := s.RunRecord.GetEntity()
	project := s.RunRecord.GetProject()
	runId := s.RunRecord.GetRunId()

	var stopResponse *service.StopStatusResponse

	// if any of the entity, project or runId is empty, we can't make the request
	if entity == "" || project == "" || runId == "" {
		s.logger.Error("sender: sendStopStatus: entity, project, runId are empty")
		stopResponse = &service.StopStatusResponse{
			RunShouldStop: false,
		}
	} else {
		response, err := gql.RunStoppedStatus(s.ctx, s.graphqlClient, &entity, &project, runId)
		switch {
		case err != nil:
			// if there is an error, we don't know if the run should stop
			err = fmt.Errorf("sender: sendStopStatus: failed to get run stopped status: %s", err)
			s.logger.CaptureError("sender received error", err)
			stopResponse = &service.StopStatusResponse{
				RunShouldStop: false,
			}
		case response == nil || response.GetProject() == nil || response.GetProject().GetRun() == nil:
			// if there is no response, we don't know if the run should stop
			stopResponse = &service.StopStatusResponse{
				RunShouldStop: false,
			}
		default:
			stopped := utils.ZeroIfNil(response.GetProject().GetRun().GetStopped())
			stopResponse = &service.StopStatusResponse{
				RunShouldStop: stopped,
			}
		}
	}

	s.respond(record,
		&service.Response{
			ResponseType: &service.Response_StopStatusResponse{
				StopStatusResponse: stopResponse,
			},
		},
	)
}

func (s *Sender) sendRequestSenderRead(_ *service.Record, _ *service.SenderReadRequest) {
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

func (s *Sender) sendRequestServerInfo(record *service.Record, _ *service.ServerInfoRequest) {
	if !s.settings.GetXOffline().GetValue() && s.serverInfo == nil {
		s.getServerInfo()
	}

	localInfo := &service.LocalInfo{}
	if s.serverInfo != nil && s.serverInfo.GetLatestLocalVersionInfo() != nil {
		localInfo = &service.LocalInfo{
			Version:   s.serverInfo.GetLatestLocalVersionInfo().GetLatestVersionString(),
			OutOfDate: s.serverInfo.GetLatestLocalVersionInfo().GetOutOfDate(),
		}
	}

	s.respond(record,
		&service.Response{
			ResponseType: &service.Response_ServerInfoResponse{
				ServerInfoResponse: &service.ServerInfoResponse{
					LocalInfo: localInfo,
				},
			},
		},
	)
}

func (s *Sender) sendRequestJobInput(request *service.JobInputRequest) {
	if s.jobBuilder == nil {
		s.logger.Warn("sender: sendJobInput: job builder disabled, skipping")
		return
	}
	s.jobBuilder.HandleJobInputRequest(request)
}
