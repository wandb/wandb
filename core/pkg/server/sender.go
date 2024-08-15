package server

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

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
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard"
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
	Settings            *settings.Settings
	Backend             *api.Backend
	FileStream          fs.FileStream
	FileTransferManager filetransfer.FileTransferManager
	FileWatcher         watcher.Watcher
	RunfilesUploader    runfiles.Uploader
	TBHandler           *tensorboard.TBHandler
	GraphqlClient       graphql.Client
	Peeker              *observability.Peeker
	RunSummary          *runsummary.RunSummary
	Mailbox             *mailbox.Mailbox
	OutChan             chan *service.Result
	OutputFileName      *paths.RelativePath
}

// Sender is the sender for a stream it handles the incoming messages and sends to the server
// or/and to the dispatcher/handler
type Sender struct {
	// runWork is the run's channel of records
	runWork runwork.RunWork

	// logger is the logger for the sender
	logger *observability.CoreLogger

	// settings is the settings for the sender
	settings *service.Settings

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

	// tbHandler integrates W&B with TensorBoard
	tbHandler *tensorboard.TBHandler

	// startState tracks the initial state of a run handling
	// potential branching with resume, fork, and rewind.
	startState *runbranch.RunParams

	// telemetry record internal implementation of telemetry
	telemetry *service.TelemetryRecord

	// runConfigMetrics tracks explicitly defined run metrics.
	runConfigMetrics *runmetric.RunConfigMetrics

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

	// networkPeeker is a helper for peeking into network responses
	networkPeeker *observability.Peeker

	// mailbox is used to store cancel functions for each mailbox slot
	mailbox *mailbox.Mailbox

	// consoleLogsSender uploads captured console output.
	consoleLogsSender *runconsolelogs.Sender
}

// NewSender creates a new Sender with the given settings
func NewSender(
	runWork runwork.RunWork,
	params SenderParams,
) *Sender {

	var outputFileName paths.RelativePath
	if params.OutputFileName != nil {
		outputFileName = *params.OutputFileName
	} else {
		// Guaranteed not to fail.
		path, _ := paths.Relative(LatestOutputFileName)
		outputFileName = *path
	}

	s := &Sender{
		runWork:             runWork,
		runConfig:           runconfig.New(),
		telemetry:           &service.TelemetryRecord{CoreVersion: version.Version},
		runConfigMetrics:    runmetric.NewRunConfigMetrics(),
		logger:              params.Logger,
		settings:            params.Settings.Proto,
		fileStream:          params.FileStream,
		fileTransferManager: params.FileTransferManager,
		fileWatcher:         params.FileWatcher,
		runfilesUploader:    params.RunfilesUploader,
		tbHandler:           params.TBHandler,
		networkPeeker:       params.Peeker,
		graphqlClient:       params.GraphqlClient,
		mailbox:             params.Mailbox,
		runSummary:          params.RunSummary,
		outChan:             params.OutChan,
		startState:          runbranch.NewRunParams(),
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

		consoleLogsSender: runconsolelogs.New(runconsolelogs.Params{
			ConsoleOutputFile: outputFileName,
			Settings:          params.Settings,
			Logger:            params.Logger,
			ExtraWork:         runWork,
			FileStreamOrNil:   params.FileStream,
		}),
	}

	backendOrNil := params.Backend
	if !s.settings.GetXOffline().GetValue() && backendOrNil != nil && !s.settings.GetDisableJobCreation().GetValue() {
		s.jobBuilder = launch.NewJobBuilder(s.settings, s.logger, false)
	}

	return s
}

// Do processes all records on the input channel.
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
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: respond: nil response"))
	default:
		s.logger.CaptureFatalAndPanic(
			fmt.Errorf("sender: respond: unexpected type %T", x))
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

	s.runWork.AddRecord(record)
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
		s.sendExit(record)
	case *service.Record_Alert:
		s.sendAlert(record, x.Alert)
	case *service.Record_Metric:
		s.sendMetric(x.Metric)
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
	case *service.Record_UseArtifact:
		s.sendUseArtifact(record)
	case *service.Record_Artifact:
		s.sendArtifact(record, x.Artifact)
	case nil:
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: sendRecord: nil RecordType"))
	default:
		s.logger.CaptureFatalAndPanic(
			fmt.Errorf("sender: sendRecord: unexpected type %T", x))
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
	case *service.Request_LinkArtifact:
		s.sendLinkArtifact(record, x.LinkArtifact)
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
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: sendRequest: nil RequestType"))
	default:
		s.logger.CaptureFatalAndPanic(
			fmt.Errorf("sender: sendRequest: unexpected type %T", x))
	}
}

// updateSettings updates the settings from the run record upon a run start
// with the information from the server
func (s *Sender) updateSettings() {
	if s.settings == nil || !s.startState.Intialized {
		return
	}

	// StartTime should be generally thought of as the Run last modified time
	// as it gets updated at a run branching point, such as resume, fork, or rewind
	if s.settings.XStartTime == nil && !s.startState.StartTime.IsZero() {
		startTime := float64(s.startState.StartTime.UnixNano()) / 1e9
		s.settings.XStartTime = &wrapperspb.DoubleValue{Value: startTime}
	}

	// TODO: verify that this is the correct update logic
	if s.startState.Entity != "" {
		s.settings.Entity = &wrapperspb.StringValue{
			Value: s.startState.Entity,
		}
	}
	if s.startState.Project != "" {
		s.settings.Project = &wrapperspb.StringValue{
			Value: s.startState.Project,
		}
	}
	if s.startState.DisplayName != "" {
		s.settings.RunName = &wrapperspb.StringValue{
			Value: s.startState.DisplayName,
		}
	}
}

// sendRequestRunStart sends a run start request to start all the stream
// components that need to be started and to update the settings
func (s *Sender) sendRequestRunStart(_ *service.RunStartRequest) {
	s.updateSettings()

	if s.fileStream != nil {
		s.fileStream.Start(
			s.startState.Entity,
			s.startState.Project,
			s.startState.RunID,
			s.startState.FileStreamOffset,
		)
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

	output := s.runSummary.ToNestedMaps()

	artifact, err := s.jobBuilder.Build(
		s.runWork.BeforeEndCtx(),
		s.graphqlClient,
		output,
	)
	if err != nil {
		s.logger.Error(
			"sender: sendDefer: failed to build job artifact", "error", err,
		)
		return
	}
	if artifact == nil {
		s.logger.Info("sender: sendDefer: no job artifact to save")
		return
	}
	saver := artifacts.NewArtifactSaver(
		s.runWork.BeforeEndCtx(),
		s.logger,
		s.graphqlClient,
		s.fileTransferManager,
		artifact,
		0,
		"",
	)
	if _, err = saver.Save(); err != nil {
		s.logger.Error(
			"sender: sendDefer: failed to save job artifact", "error", err,
		)
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
		s.tbHandler.Finish()
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_SUM:
		s.summaryDebouncer.Flush(s.streamSummary)
		s.summaryDebouncer.Stop()
		s.uploadSummaryFile()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_DEBOUNCER:
		s.configDebouncer.SetNeedsDebounce()
		s.configDebouncer.Flush(s.upsertConfig)
		s.configDebouncer.Stop()
		s.uploadConfigFile()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_OUTPUT:
		s.consoleLogsSender.Finish()
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
			if s.exitRecord != nil {
				s.fileStream.FinishWithExit(s.exitRecord.GetExit().GetExitCode())
			} else {
				s.logger.CaptureError(
					fmt.Errorf("sender: no exit code on finish"))
				s.fileStream.FinishWithoutExit()
			}
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

		s.runWork.SetDone()
	default:
		s.logger.CaptureFatalAndPanic(
			fmt.Errorf("sender: sendDefer: unexpected state %v", request.State))
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

func (s *Sender) sendLinkArtifact(record *service.Record, msg *service.LinkArtifactRequest) {
	var response service.LinkArtifactResponse
	linker := artifacts.ArtifactLinker{
		Ctx:           s.runWork.BeforeEndCtx(),
		Logger:        s.logger,
		LinkArtifact:  msg,
		GraphqlClient: s.graphqlClient,
	}
	err := linker.Link()
	if err != nil {
		response.ErrorMessage = err.Error()
		s.logger.CaptureError(err)
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_LinkArtifactResponse{
					LinkArtifactResponse: &response,
				},
			},
		},
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

// Inserts W&B-internal information into the run configuration.
func (s *Sender) updateConfigPrivate() {
	s.runConfig.AddTelemetryAndMetrics(
		s.telemetry,
		s.runConfigMetrics.ToRunConfigData(),
	)
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

func (s *Sender) sendForkRun(record *service.Record, _ *service.RunRecord) {
	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Code:    service.ErrorInfo_UNSUPPORTED,
				Message: "`fork_from` is not yet supported",
			},
		}
		s.respond(record, result)
	}
}

func (s *Sender) sendRewindRun(record *service.Record, _ *service.RunRecord) {
	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Code:    service.ErrorInfo_UNSUPPORTED,
				Message: "`resume_from` is not yet supported",
			},
		}
		s.respond(record, result)
	}
}

func (s *Sender) sendResumeRun(record *service.Record, run *service.RunRecord) {

	update, err := runbranch.NewResumeBranch(
		s.runWork.BeforeEndCtx(),
		s.graphqlClient,
		s.settings.GetResume().GetValue(),
	).GetUpdates(s.startState, runbranch.RunPath{
		Entity:  s.startState.Entity,
		Project: s.startState.Project,
		RunID:   s.startState.RunID,
	})

	if err != nil {
		s.logger.CaptureError(
			fmt.Errorf("send: sendRun: failed to update run state: %s", err),
		)
		// provide more info about the error to the user
		if errType, ok := err.(*runbranch.BranchError); ok {
			if errType.Response != nil {
				if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
					result := &service.RunUpdateResult{
						Error: errType.Response,
					}
					s.respond(record, result)
				}
				return
			}
		}
	}
	s.startState.Merge(update)

	// On the first invocation of sendRun, we overwrite the tags if the user
	// has set them in wandb.init(). Otherwise, we keep the tags from the
	// original run.
	if len(run.Tags) == 0 {
		run.Tags = append(run.Tags, s.startState.Tags...)
	}

	// Merge the resumed config into the run config
	s.runConfig.MergeResumedConfig(s.startState.Config)

	proto.Merge(run, s.startState.Proto())
	s.upsertRun(record, run)
}

// sendRun sends a run record to the server and updates the run record
func (s *Sender) sendRun(record *service.Record, run *service.RunRecord) {
	// TODO: we use the same record type for the initial run upsert and the
	//  follow-up run updates, such as setting the name, tags, and notes.
	//  The client only expects a response for the initial upsert, the
	//  consequent updates are fire-and-forget and thus don't have a mailbox
	//  slot.
	//  We should probably separate the initial upsert from the updates.

	var ok bool
	runClone, ok := proto.Clone(run).(*service.RunRecord)
	if !ok {
		err := errors.New("failed to clone run record")
		s.logger.CaptureFatalAndPanic(
			fmt.Errorf("send: sendRun: failed to send run: %s", err),
		)
	}

	// if there is no graphql client, we don't need to do anything
	if s.graphqlClient == nil {
		if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
			s.respond(record,
				&service.RunUpdateResult{
					Run: runClone,
				})
		}
		return
	}

	// The first run record sent by the client is encoded incorrectly,
	// causing it to overwrite the entire "_wandb" config key rather than
	// just the necessary part ("_wandb/code_path"). This can overwrite
	// the config from a resumed run, so we have to do this first.
	//
	// Logically, it would make more sense to instead start with the
	// resumed config and apply updates on top of it.
	s.runConfig.ApplyChangeRecord(run.Config,
		func(err error) {
			s.logger.CaptureError(
				fmt.Errorf("error updating run config: %v", err))
		})

	proto.Merge(s.telemetry, run.Telemetry)
	s.updateConfigPrivate()

	if !s.startState.Intialized {
		s.startState.Intialized = true

		// update the run state with the initial run record
		s.startState.Merge(&runbranch.RunParams{
			RunID:       runClone.GetRunId(),
			Project:     runClone.GetProject(),
			Entity:      runClone.GetEntity(),
			DisplayName: runClone.GetDisplayName(),
			StorageID:   runClone.GetStorageId(),
			SweepID:     runClone.GetSweepId(),
			StartTime:   runClone.GetStartTime().AsTime(),
		})

		isResume := s.settings.GetResume().GetValue()
		isRewind := s.settings.GetResumeFrom()
		isFork := s.settings.GetForkFrom()
		switch {
		case isResume != "" && isRewind != nil || isResume != "" && isFork != nil || isRewind != nil && isFork != nil:
			if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
				result := &service.RunUpdateResult{
					Error: &service.ErrorInfo{
						Code: service.ErrorInfo_USAGE,
						Message: "`resume`, `fork_from`, and `resume_from` are mutually exclusive. " +
							"Please specify only one of them.",
					},
				}
				s.respond(record, result)
			}
			s.logger.Error("sender: sendRun: user provided more than one of resume, rewind, or fork")
			return
		case isResume != "":
			s.sendResumeRun(record, runClone)
			return
		case isRewind != nil:
			s.sendRewindRun(record, runClone)
			return
		case isFork != nil:
			s.sendForkRun(record, runClone)
			return
		default:
			// no resume, rewind, or fork provided
		}
	}

	s.upsertRun(record, runClone)
}

func (s *Sender) upsertRun(record *service.Record, run *service.RunRecord) {
	// start a new context with an additional argument from the parent context
	// this is used to pass the retry function to the graphql client
	ctx := context.WithValue(
		s.runWork.BeforeEndCtx(),
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)

	// if the record has a mailbox slot, create a new cancelable context
	// and store the cancel function in the message registry so that
	// the context can be canceled if requested by the client
	mailboxSlot := record.GetControl().GetMailboxSlot()
	if mailboxSlot != "" {
		// if this times out, we mark the run as done as there is
		// no need to proceed with it
		ctx = s.mailbox.Add(ctx, s.runWork.SetDone, mailboxSlot)
	} else if !s.startState.Intialized {
		// this should never happen:
		// the initial run upsert record should have a mailbox slot set by the client
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: upsertRun: mailbox slot not set"),
		)
	}

	config, _ := s.serializeConfig(runconfig.FormatJson)

	var commit, repo string
	git := run.GetGit()
	if git != nil {
		commit = git.GetCommit()
		repo = git.GetRemoteUrl()
	}

	program := s.settings.GetProgram().GetValue()

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
		run.Tags,                         // tags []string,
		nil,                              // summaryMetrics
	)

	if err != nil {
		err = fmt.Errorf("failed to upsert bucket: %s", err)
		s.logger.Error("sender: upsertRun:", "error", err)
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

	// manage the state of the run
	if data == nil || data.GetUpsertBucket() == nil || data.GetUpsertBucket().GetBucket() == nil {
		s.logger.Error("sender: upsertRun: upsert bucket response is empty")
	} else {
		bucket := data.GetUpsertBucket().GetBucket()

		project := bucket.GetProject()
		var projectName, entityName string
		if project == nil {
			s.logger.Error("sender: upsertRun: project is nil")
		} else {
			entity := project.GetEntity()
			entityName = entity.GetName()
			projectName = project.GetName()
		}
		s.startState.Merge(&runbranch.RunParams{
			StorageID:   bucket.GetId(),
			Entity:      utils.ZeroIfNil(&entityName),
			Project:     utils.ZeroIfNil(&projectName),
			RunID:       bucket.GetName(),
			DisplayName: utils.ZeroIfNil(bucket.GetDisplayName()),
			SweepID:     utils.ZeroIfNil(bucket.GetSweepName()),
		})
	}

	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
		// This will be done only for the initial run upsert record
		// the consequent updates are fire-and-forget
		proto.Merge(run, s.startState.Proto())
		s.respond(record,
			&service.RunUpdateResult{
				Run: run,
			},
		)
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

	update, err := s.runSummary.ToRecords()

	// `update` may be non-empty even on error.
	if err != nil {
		s.logger.CaptureError(
			fmt.Errorf("sender: error flattening summary: %v", err))
	}

	s.fileStream.StreamUpdate(&fs.SummaryUpdate{
		Record: &service.SummaryRecord{Update: update},
	})
}

func (s *Sender) sendSummary(_ *service.Record, summary *service.SummaryRecord) {
	for _, update := range summary.Update {
		if err := s.runSummary.SetFromRecord(update); err != nil {
			s.logger.CaptureError(
				fmt.Errorf("sender: error updating summary: %v", err))
		}
	}

	for _, remove := range summary.Remove {
		s.runSummary.RemoveFromRecord(remove)
	}

	s.summaryDebouncer.SetNeedsDebounce()
}

func (s *Sender) upsertConfig() {
	if s.graphqlClient == nil {
		return
	}
	if !s.startState.Intialized {
		s.logger.Error("sender: upsertConfig: RunRecord is nil")
		return
	}

	s.updateConfigPrivate()
	config, err := s.serializeConfig(runconfig.FormatJson)
	if err != nil {
		s.logger.Error("sender: upsertConfig: failed to serialize config", "error", err)
		return
	}
	if config == "" {
		return
	}

	ctx := context.WithValue(
		s.runWork.BeforeEndCtx(),
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)
	_, err = gql.UpsertBucket(
		ctx,                                   // ctx
		s.graphqlClient,                       // client
		nil,                                   // id
		&s.startState.RunID,                   // name
		utils.NilIfZero(s.startState.Project), // project
		utils.NilIfZero(s.startState.Entity),  // entity
		nil,                                   // groupName
		nil,                                   // description
		nil,                                   // displayName
		nil,                                   // notes
		nil,                                   // commit
		&config,                               // config
		nil,                                   // host
		nil,                                   // debug
		nil,                                   // program
		nil,                                   // repo
		nil,                                   // jobType
		nil,                                   // state
		nil,                                   // sweep
		nil,                                   // tags []string,
		nil,                                   // summaryMetrics
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
				s.logger.CaptureError(
					fmt.Errorf("error updating run config: %v", err))
			})
	}
	s.configDebouncer.SetNeedsDebounce()
}

// sendSystemMetrics sends a system metrics record via the file stream
func (s *Sender) sendSystemMetrics(record *service.StatsRecord) {
	if s.fileStream == nil {
		return
	}

	// This is a sanity check to ensure that the start time is set
	// before sending system metrics, it should always be set
	// when the run is initialized
	// If it's not set, we log an error and return
	if s.startState.StartTime.IsZero() {
		s.logger.CaptureError(
			fmt.Errorf("sender: sendSystemMetrics: start time not set"),
			"startState",
			s.startState,
		)
		return
	}

	s.fileStream.StreamUpdate(&fs.StatsUpdate{
		StartTime: s.startState.StartTime,
		Record:    record})
}

func (s *Sender) sendOutput(_ *service.Record, _ *service.OutputRecord) {
	// TODO: implement me
}

func (s *Sender) sendOutputRaw(_ *service.Record, outputRaw *service.OutputRawRecord) {
	s.consoleLogsSender.StreamLogs(outputRaw)
}

func (s *Sender) sendAlert(_ *service.Record, alert *service.AlertRecord) {
	if s.graphqlClient == nil {
		return
	}

	if !s.startState.Intialized {
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: sendAlert: RunRecord not set"))
	}
	// TODO: handle invalid alert levels
	severity := gql.AlertSeverity(alert.Level)

	data, err := gql.NotifyScriptableRunAlert(
		s.runWork.BeforeEndCtx(),
		s.graphqlClient,
		s.startState.Entity,
		s.startState.Project,
		s.startState.RunID,
		alert.Title,
		alert.Text,
		&severity,
		&alert.WaitDuration,
	)
	if err != nil {
		s.logger.CaptureError(
			fmt.Errorf(
				"sender: sendAlert: failed to notify scriptable run alert: %v",
				err,
			))
	} else {
		s.logger.Info("sender: sendAlert: notified scriptable run alert", "data", data)
	}

}

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(record *service.Record) {
	// response is done by respond() and called when defer state machine is complete
	s.exitRecord = record

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

// sendMetric updates the metrics in the run config.
func (s *Sender) sendMetric(metric *service.MetricRecord) {
	err := s.runConfigMetrics.ProcessRecord(metric)

	if err != nil {
		s.logger.CaptureError(fmt.Errorf("sender: sendMetric: %v", err))
		return
	}

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
		s.runWork.BeforeEndCtx(),
		s.logger,
		s.graphqlClient,
		s.fileTransferManager,
		msg,
		0,
		"",
	)
	artifactID, err := saver.Save()
	if err != nil {
		err = fmt.Errorf("sender: sendArtifact: failed to log artifact ID: %s; error: %s", artifactID, err)
		s.logger.Error("sender: sendArtifact:", "error", err)
		return
	}
}

func (s *Sender) sendRequestLogArtifact(record *service.Record, msg *service.LogArtifactRequest) {
	var response service.LogArtifactResponse
	saver := artifacts.NewArtifactSaver(
		s.runWork.BeforeEndCtx(),
		s.logger,
		s.graphqlClient,
		s.fileTransferManager,
		msg.Artifact,
		msg.HistoryStep,
		msg.StagingDir,
	)
	artifactID, err := saver.Save()
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
	var response service.DownloadArtifactResponse

	if s.graphqlClient == nil {
		// Offline mode handling:
		s.logger.Error("sender: sendRequestDownloadArtifact: cannot download artifact in offline mode")
		response.ErrorMessage = "Artifact downloads are not supported in offline mode."
	} else if err := artifacts.NewArtifactDownloader(
		s.runWork.BeforeEndCtx(),
		s.graphqlClient,
		s.fileTransferManager,
		msg.ArtifactId,
		msg.DownloadRoot,
		msg.AllowMissingReferences,
		msg.SkipCache,
		msg.PathPrefix,
	).Download(); err != nil {
		// Online mode handling: error during download
		s.logger.CaptureError(
			fmt.Errorf("sender: failed to download artifact: %v", err))
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

	s.syncService = NewSyncService(
		s.runWork.BeforeEndCtx(),
		WithSyncServiceLogger(s.logger),
		WithSyncServiceSenderFunc(s.sendRecord), // TODO: pass runWork here (as ExtraWork)
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
			if !s.startState.Intialized {
				baseUrl := s.settings.GetBaseUrl().GetValue()
				baseUrl = strings.Replace(baseUrl, "api.", "", 1)
				url = fmt.Sprintf("%s/%s/%s/runs/%s",
					baseUrl,
					s.startState.Entity,
					s.startState.Project,
					s.startState.RunID,
				)
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
	entity := s.startState.Entity
	project := s.startState.Project
	runId := s.startState.RunID

	var stopResponse *service.StopStatusResponse

	// if any of the entity, project or runId is empty, we can't make the request
	if entity == "" || project == "" || runId == "" {
		s.logger.Error("sender: sendStopStatus: entity, project, runId are empty")
		stopResponse = &service.StopStatusResponse{
			RunShouldStop: false,
		}
	} else {
		response, err := gql.RunStoppedStatus(
			s.runWork.BeforeEndCtx(),
			s.graphqlClient,
			&entity,
			&project,
			runId,
		)
		switch {
		case err != nil:
			// if there is an error, we don't know if the run should stop
			s.logger.CaptureError(
				fmt.Errorf(
					"sender: sendStopStatus: failed to get run stopped status: %v",
					err,
				))
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
		store := NewStore(s.settings.GetSyncFile().GetValue())
		err := store.Open(os.O_RDONLY)
		if err != nil {
			s.logger.CaptureError(
				fmt.Errorf(
					"sender: sendSenderRead: failed to create store: %v",
					err,
				))
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
			s.logger.CaptureError(
				fmt.Errorf(
					"sender: sendSenderRead: failed to read record: %v",
					err,
				))
			return
		}
	}
}

// sendRequestServerInfo sends a server info request to the server to probe the server for
// version compatibility and other server information
func (s *Sender) sendRequestServerInfo(record *service.Record, _ *service.ServerInfoRequest) {

	// if there is no graphql client, we don't need to do anything
	// just respond with an empty server info response
	if s.graphqlClient == nil {
		s.respond(record,
			&service.Response{
				ResponseType: &service.Response_ServerInfoResponse{
					ServerInfoResponse: &service.ServerInfoResponse{},
				},
			},
		)
		return
	}

	// if we don't have server info, get it from the server
	if s.serverInfo == nil {
		data, err := gql.ServerInfo(s.runWork.BeforeEndCtx(), s.graphqlClient)
		// if there is an error, we don't know the server info
		// respond with an empty server info response
		// this is a best effort to get the server info
		if err != nil {
			s.logger.Error(
				"sender: getServerInfo: failed to get server info", "error", err,
			)
			s.respond(record,
				&service.Response{
					ResponseType: &service.Response_ServerInfoResponse{
						ServerInfoResponse: &service.ServerInfoResponse{},
					},
				},
			)
			return
		}
		s.serverInfo = data.GetServerInfo()
		s.logger.Info("sender: getServerInfo: got server info", "serverInfo", s.serverInfo)
	}

	// if we have server info, respond with the server info
	// this is a best effort to get the server info
	latestVersion := s.serverInfo.GetLatestLocalVersionInfo()
	if latestVersion != nil {
		s.respond(record,
			&service.Response{
				ResponseType: &service.Response_ServerInfoResponse{
					ServerInfoResponse: &service.ServerInfoResponse{
						LocalInfo: &service.LocalInfo{
							Version:   latestVersion.GetLatestVersionString(),
							OutOfDate: latestVersion.GetOutOfDate(),
						},
					},
				},
			},
		)
		return
	}

	// default response if we don't have server info
	s.respond(record,
		&service.Response{
			ResponseType: &service.Response_ServerInfoResponse{
				ServerInfoResponse: &service.ServerInfoResponse{},
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
