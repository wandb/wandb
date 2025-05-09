package stream

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/internal/featurechecker"
	fs "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
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
	"github.com/wandb/wandb/core/internal/wboperation"
	"github.com/wandb/wandb/core/pkg/artifacts"
	"github.com/wandb/wandb/core/pkg/launch"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	configDebouncerRateLimit  = 1 / 30.0 // todo: audit rate limit
	configDebouncerBurstSize  = 1        // todo: audit burst size
	summaryDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	summaryDebouncerBurstSize = 1        // todo: audit burst size
	ConsoleFileName           = "output.log"
)

type SenderParams struct {
	Logger              *observability.CoreLogger
	Operations          *wboperation.WandbOperations
	Settings            *settings.Settings
	Backend             *api.Backend
	FeatureProvider     *featurechecker.ServerFeaturesCache
	FileStream          fs.FileStream
	FileTransferManager filetransfer.FileTransferManager
	FileTransferStats   filetransfer.FileTransferStats
	FileWatcher         watcher.Watcher
	RunfilesUploader    runfiles.Uploader
	TBHandler           *tensorboard.TBHandler
	GraphqlClient       graphql.Client
	Peeker              *observability.Peeker
	RunSummary          *runsummary.RunSummary
	Mailbox             *mailbox.Mailbox
	OutChan             chan *spb.Result
	RunWork             runwork.RunWork
}

// senderSentinel is used when flushing buffered work while finalizing a run.
type senderSentinel int64

// String returns a string representation of senderSentinel for debugging.
func (s senderSentinel) String() string {
	return fmt.Sprintf("senderSentinel(%d)", s)
}

// Sender is the sender for a stream it handles the incoming messages and sends to the server
// or/and to the dispatcher/handler
type Sender struct {
	// mu is a coarse mutex for accessing non-threadsafe Sender state.
	//
	// It is locked while processing a Record and at specific times during
	// the finishRun goroutine to guard anything that's not threadsafe.
	mu sync.Mutex

	// sentinelSent is the largest sentinel value pushed to runWork, incremented
	// by 1 each time.
	//
	// sentinelSeen is the largest sentinel value observed on the input channel.
	//
	// It is always true that sentinelSent >= sentinelSeen.
	//
	// mu must be held when accessing either field.
	sentinelSent, sentinelSeen senderSentinel

	// sentinelCond is broadcast whenever sentinelSeen updates.
	//
	// The underlying mutex is mu.
	sentinelCond *sync.Cond

	// runWork is the run's channel of records
	runWork runwork.RunWork

	// logger is the logger for the sender
	logger *observability.CoreLogger

	operations *wboperation.WandbOperations

	// settings is the settings for the sender
	settings *settings.Settings

	// outChan is the channel for dispatcher messages
	outChan chan *spb.Result

	// graphqlClient is the graphql client
	graphqlClient graphql.Client

	// fileStream is the file stream
	fileStream fs.FileStream

	// fileTransferManager is the file uploader/downloader
	fileTransferManager filetransfer.FileTransferManager

	// fileTransferStats tracks file upload progress
	fileTransferStats filetransfer.FileTransferStats

	// fileWatcher notifies when files in the file system are changed
	fileWatcher watcher.Watcher

	// runfilesUploader manages uploading a run's files
	runfilesUploader runfiles.Uploader

	// artifactsSaver manages artifact uploads
	artifactsSaver *artifacts.ArtifactSaveManager

	// artifactWG is a wait group for artifact-related goroutines
	artifactWG sync.WaitGroup

	// tbHandler integrates W&B with TensorBoard
	tbHandler *tensorboard.TBHandler

	// startState tracks the initial state of a run handling
	// potential branching with resume, fork, and rewind.
	//
	// It is nil initially.
	startState *runbranch.RunParams

	// telemetry record internal implementation of telemetry
	telemetry *spb.TelemetryRecord

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

	// Keep track of exit record to pass to file stream when the time comes
	exitRecord *spb.Record

	// Keep track of sync finish record to pass to file stream when the time comes
	syncFinishRecord *spb.Record

	// Keep track of finishWithoutExitRecord to pass to file stream if and when the time comes
	finishWithoutExitRecord *spb.Record

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
	params SenderParams,
) *Sender {

	var outputFileName paths.RelativePath
	// Guaranteed not to fail.
	path, _ := paths.Relative(ConsoleFileName)
	outputFileName = *path

	if params.Settings.GetLabel() != "" {
		sanitizedLabel := fileutil.SanitizeFilename(params.Settings.GetLabel())
		// Guaranteed not to fail.
		// split filename and extension
		extension := filepath.Ext(string(outputFileName))
		path, _ := paths.Relative(
			fmt.Sprintf(
				"%s_%s%s",
				strings.TrimSuffix(string(outputFileName), extension),
				sanitizedLabel,
				extension,
			),
		)
		outputFileName = *path
	}

	// If console capture is enabled, we need to create a multipart console log file.
	if params.Settings.IsConsoleMultipart() {
		// This is guaranteed not to fail.
		timestamp := time.Now()
		extension := filepath.Ext(string(outputFileName))
		path, _ := paths.Relative(
			filepath.Join(
				"logs",
				fmt.Sprintf(
					"%s_%s_%09d%s",
					strings.TrimSuffix(string(outputFileName), extension),
					timestamp.Format("20060102_150405"),
					timestamp.Nanosecond(),
					extension,
				),
			),
		)
		outputFileName = *path
	}

	consoleLogsSenderParams := runconsolelogs.Params{
		ConsoleOutputFile:     outputFileName,
		FilesDir:              params.Settings.GetFilesDir(),
		EnableCapture:         params.Settings.IsConsoleCaptureEnabled(),
		Logger:                params.Logger,
		FileStreamOrNil:       params.FileStream,
		Label:                 params.Settings.GetLabel(),
		RunfilesUploaderOrNil: params.RunfilesUploader,
		Structured: params.FeatureProvider.GetFeature(
			spb.ServerFeature_STRUCTURED_CONSOLE_LOGS,
		).Enabled,
	}

	// If the server doesn't support expanding defined metric globs, and the user
	// has requested it, we default to the client-side expansion of defined metric
	// globs.
	serverSupportsExpandGlobMetrics := params.FeatureProvider.GetFeature(
		spb.ServerFeature_EXPAND_DEFINED_METRIC_GLOBS,
	).Enabled
	if !serverSupportsExpandGlobMetrics &&
		params.Settings.IsEnableServerSideExpandGlobMetrics() {
		params.Logger.Warn(
			"server does not support expanding defined metric globs, defaulting to client-side expansion",
		)
	}

	s := &Sender{
		runWork:   params.RunWork,
		runConfig: runconfig.New(),
		telemetry: &spb.TelemetryRecord{CoreVersion: version.Version},
		runConfigMetrics: runmetric.NewRunConfigMetrics(
			serverSupportsExpandGlobMetrics &&
				params.Settings.IsEnableServerSideExpandGlobMetrics(),
		),
		logger:              params.Logger,
		operations:          params.Operations,
		settings:            params.Settings,
		fileStream:          params.FileStream,
		fileTransferManager: params.FileTransferManager,
		fileTransferStats:   params.FileTransferStats,
		fileWatcher:         params.FileWatcher,
		runfilesUploader:    params.RunfilesUploader,
		artifactsSaver: artifacts.NewArtifactSaveManager(
			params.Logger,
			params.GraphqlClient,
			params.FileTransferManager,
			params.FeatureProvider.GetFeature(
				spb.ServerFeature_USE_ARTIFACT_WITH_ENTITY_AND_PROJECT_INFORMATION,
			).Enabled,
		),
		tbHandler:     params.TBHandler,
		networkPeeker: params.Peeker,
		graphqlClient: params.GraphqlClient,
		mailbox:       params.Mailbox,
		runSummary:    params.RunSummary,
		outChan:       params.OutChan,
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
		consoleLogsSender: runconsolelogs.New(consoleLogsSenderParams),
	}

	s.sentinelCond = sync.NewCond(&s.mu)

	backendOrNil := params.Backend
	if !s.settings.IsOffline() && backendOrNil != nil && !s.settings.IsJobCreationDisabled() {
		s.jobBuilder = launch.NewJobBuilder(s.settings.Proto, s.logger, false)
	}

	return s
}

// Do processes all work on the input channel.
func (s *Sender) Do(allWork <-chan runwork.Work) {
	defer s.logger.Reraise()
	s.logger.Info("sender: started", "stream_id", s.settings.GetRunID())

	hangDetectionInChan := make(chan runwork.Work, 32)
	hangDetectionOutChan := make(chan struct{}, 32)
	go s.warnOnLongOperations(hangDetectionInChan, hangDetectionOutChan)

	for work := range allWork {
		hangDetectionInChan <- work

		s.logger.Debug(
			"sender: got work",
			"work", work,
			"stream_id", s.settings.GetRunID(),
		)

		s.mu.Lock()
		work.Process(s.sendRecord)
		s.observeSentinel(work)

		// TODO: reevaluate the logic here
		s.configDebouncer.Debounce(s.upsertConfig)
		s.summaryDebouncer.Debounce(s.streamSummary)
		s.mu.Unlock()

		hangDetectionOutChan <- struct{}{}
	}

	close(hangDetectionInChan)
	close(hangDetectionOutChan)

	s.Close()
	s.logger.Info("sender: closed", "stream_id", s.settings.GetRunID())
}

// warnOnLongOperations logs a warning for each message received
// on the first channel for which no message is received on the second
// channel within some time.
func (s *Sender) warnOnLongOperations(
	hangDetectionInChan <-chan runwork.Work,
	hangDetectionOutChan <-chan struct{},
) {
outerLoop:
	for work := range hangDetectionInChan {
		start := time.Now()

		for i := 0; ; i++ {
			select {
			case <-hangDetectionOutChan:
				if i > 0 {
					s.logger.CaptureInfo(
						"sender: succeeded after taking longer than expected",
						"seconds", time.Since(start).Seconds(),
						"work", work.DebugInfo(),
					)
				}

				continue outerLoop

			case <-time.After(10 * time.Minute):
				if i < 6 {
					s.logger.CaptureWarn(
						"sender: taking a long time",
						"seconds", time.Since(start).Seconds(),
						"work", work.DebugInfo(),
					)
				}
			}
		}
	}

}

func (s *Sender) Close() {
	// sender is done processing data, close our dispatch channel
	close(s.outChan)
}

func (s *Sender) respond(record *spb.Record, response any) {
	if record == nil {
		s.logger.Error("sender: respond: nil record")
		return
	}

	switch x := response.(type) {
	case *spb.Response:
		s.respondResponse(record, x)
	case *spb.RunExitResult:
		s.respondExit(record, x)
	case *spb.RunUpdateResult:
		s.respondRunUpdate(record, x)
	case nil:
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: respond: nil response"))
	default:
		s.logger.CaptureFatalAndPanic(
			fmt.Errorf("sender: respond: unexpected type %T", x))
	}
}

func (s *Sender) respondRunUpdate(record *spb.Record, run *spb.RunUpdateResult) {
	result := &spb.Result{
		ResultType: &spb.Result_RunResult{RunResult: run},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.outChan <- result
}

// respondResponse responds to a response record
func (s *Sender) respondResponse(record *spb.Record, response *spb.Response) {
	result := &spb.Result{
		ResultType: &spb.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.outChan <- result
}

// respondExit responds to an exit record
func (s *Sender) respondExit(record *spb.Record, exit *spb.RunExitResult) {
	if !s.exitRecord.Control.ReqResp && s.exitRecord.Control.MailboxSlot == "" {
		return
	}
	result := &spb.Result{
		ResultType: &spb.Result_ExitResult{ExitResult: exit},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.outChan <- result
}

func (s *Sender) SendRecord(record *spb.Record) {
	// this is for testing purposes only yet
	s.sendRecord(record)
}

// sendRecord sends a record
//
//gocyclo:ignore
func (s *Sender) sendRecord(record *spb.Record) {
	switch x := record.RecordType.(type) {
	case *spb.Record_Header:
		// no-op
	case *spb.Record_Footer:
		// no-op
	case *spb.Record_Final:
		// no-op
	case *spb.Record_Run:
		s.sendRun(record, x.Run)
	case *spb.Record_Exit:
		s.sendExit(record)
	case *spb.Record_Alert:
		s.sendAlert(record, x.Alert)
	case *spb.Record_Metric:
		s.sendMetric(record, x.Metric)
	case *spb.Record_Files:
		s.sendFiles(record, x.Files)
	case *spb.Record_History:
		s.sendHistory(x.History)
	case *spb.Record_Summary:
		s.sendSummary(record, x.Summary)
	case *spb.Record_Config:
		s.sendConfig(record, x.Config)
	case *spb.Record_Stats:
		s.sendSystemMetrics(x.Stats)
	case *spb.Record_OutputRaw:
		s.sendOutputRaw(record, x.OutputRaw)
	case *spb.Record_Output:
		s.sendOutput(record, x.Output)
	case *spb.Record_Telemetry:
		s.sendTelemetry(record, x.Telemetry)
	case *spb.Record_Preempting:
		s.sendPreempting(x.Preempting)
	case *spb.Record_Request:
		s.sendRequest(record, x.Request)
	case *spb.Record_UseArtifact:
		s.sendUseArtifact(record)
	case *spb.Record_Artifact:
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
func (s *Sender) sendRequest(record *spb.Record, request *spb.Request) {
	switch x := request.RequestType.(type) {
	case *spb.Request_ServerInfo:
	case *spb.Request_CheckVersion:
		// These requests were removed from the client, so we don't need to
		// handle them. Keep for now should be removed in the future
	case *spb.Request_RunStart:
		s.sendRequestRunStart(x.RunStart)
	case *spb.Request_NetworkStatus:
		s.sendRequestNetworkStatus(record, x.NetworkStatus)
	case *spb.Request_LogArtifact:
		s.sendRequestLogArtifact(record, x.LogArtifact)
	case *spb.Request_LinkArtifact:
		s.sendLinkArtifact(record, x.LinkArtifact)
	case *spb.Request_DownloadArtifact:
		s.sendRequestDownloadArtifact(record, x.DownloadArtifact)
	case *spb.Request_SyncFinish:
		s.sendRequestSyncFinish(record, x.SyncFinish)
	case *spb.Request_SenderRead:
		// TODO: implement this
	case *spb.Request_StopStatus:
		s.sendRequestStopStatus(record, x.StopStatus)
	case *spb.Request_JobInput:
		s.sendRequestJobInput(x.JobInput)
	case *spb.Request_RunFinishWithoutExit:
		s.sendRequestRunFinishWithoutExit(record, x.RunFinishWithoutExit)
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
	if s.startState == nil {
		s.logger.CaptureError(
			errors.New("sender: updateSettings: no start state"))
		return
	}

	// StartTime should be generally thought of as the Run last modified time
	// as it gets updated at a run branching point, such as resume, fork, or rewind
	if s.settings.GetStartTime().IsZero() && !s.startState.StartTime.IsZero() {
		s.settings.UpdateStartTime(s.startState.StartTime)
	}

	// TODO: verify that this is the correct update logic
	if s.startState.Entity != "" {
		s.settings.UpdateEntity(s.startState.Entity)
	}
	if s.startState.Project != "" {
		s.settings.UpdateProject(s.startState.Project)
	}
	if s.startState.DisplayName != "" {
		s.settings.UpdateDisplayName(s.startState.DisplayName)
	}
}

// sendRequestRunStart sends a run start request to start all the stream
// components that need to be started and to update the settings
func (s *Sender) sendRequestRunStart(_ *spb.RunStartRequest) {
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
	record *spb.Record,
	_ *spb.NetworkStatusRequest,
) {
	// in case of network peeker is not set, we don't need to do anything
	if s.networkPeeker == nil {
		return
	}

	// send the network status response if there is any
	if response := s.networkPeeker.Read(); len(response) > 0 {
		s.respond(record,
			&spb.Response{
				ResponseType: &spb.Response_NetworkStatusResponse{
					NetworkStatusResponse: &spb.NetworkStatusResponse{
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

	output := s.runSummary.ToNestedMaps()

	op := s.operations.New("saving job artifact")
	defer op.Finish()

	artifact, err := s.jobBuilder.Build(
		op.Context(s.runWork.BeforeEndCtx()),
		s.graphqlClient,
		s.runConfig.CloneTree(),
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

	result := <-s.artifactsSaver.Save(
		op.Context(s.runWork.BeforeEndCtx()),
		artifact,
		0,
		"",
	)
	if result.Err != nil {
		s.logger.CaptureError(
			fmt.Errorf("sender: failed to save job artifact: %v", result.Err))
	}
}

// startFinishRun flushes all asynchronous work and shuts down all subcomponents
// at the end of a run.
//
// Everything happens in a separate goroutine during which the Sender
// continues to process incoming work.
func (s *Sender) startFinishRun() {
	go func() {
		defer s.logger.Reraise()
		s.finishRunSync()
	}()
}

// finishRunSync implements the finishRun goroutine.
//
// The finish process happens in stages. Each stage is allowed to emit
// additional Work that is processed by later stages, `flushWork` is called
// between stages.
func (s *Sender) finishRunSync() {
	runStage := func(stage func()) {
		stage()
		s.flushWork()
	}

	// Wait to finish reading all TensorBoard tfevent files, if any.
	runStage(func() {
		s.tbHandler.Finish()
	})

	// Finish uploading captured console logs.
	runStage(func() {
		s.consoleLogsSender.Finish()
	})

	// Upload the run's finalized summary and config.
	runStage(func() {
		s.mu.Lock()
		defer s.mu.Unlock()

		s.summaryDebouncer.Flush(s.streamSummary)
		s.summaryDebouncer.Stop()
		s.uploadSummaryFile()

		s.configDebouncer.SetNeedsDebounce()
		s.configDebouncer.Flush(s.upsertConfig)
		s.configDebouncer.Stop()
		s.uploadConfigFile()
	})

	// Wait for artifacts operations to complete here to detect
	// code artifacts, then upload the code (aka "job") artifact, if any.
	runStage(func() {
		s.artifactWG.Wait() // TODO: separate stage?

		s.mu.Lock()
		s.sendJobFlush()
		s.mu.Unlock()
	})

	// Finish uploading non-artifact files.
	//
	// Order matters: we must stop watching files first, since that pushes
	// updates to the runfiles uploader. The uploader creates file upload
	// tasks, so it must be flushed before we close the file transfer
	// manager.
	runStage(func() {
		s.fileWatcher.Finish()
		if s.fileTransferManager != nil {
			s.runfilesUploader.UploadRemaining()
			s.runfilesUploader.Finish()
			s.fileTransferManager.Close()
		}
	})

	// Mark the run finished.
	if s.fileStream != nil {
		runStage(s.finishFileStream)
	}

	// From this point on, no new work may be generated by this function.

	// Indicate that `run.finish()` is done.
	//
	// TODO: Remove this once deemed safe. It was used in the old code for
	// printing `run.finish()` progress, and it was necessary to "close"
	// the progress bar shown in Jupyter. Yes, that was the only purpose.
	s.fileTransferStats.SetDone()

	// Respond to the client's exit record, if necessary.
	//
	// Not necessary when syncing as the exit record is in the transaction log
	// and the client is not waiting on a response.
	//
	// TODO: add logic to handle the case where the exit record is not present
	//       in the transaction log.
	switch {
	case !s.settings.IsSync() && s.exitRecord != nil:
		s.respond(s.exitRecord, &spb.RunExitResult{})
	case !s.settings.IsSync() && s.finishWithoutExitRecord != nil:
		response := &spb.Response{
			ResponseType: &spb.Response_RunFinishWithoutExitResponse{},
		}
		s.respond(s.finishWithoutExitRecord, response)
	case s.settings.IsSync() && s.syncFinishRecord != nil:
		s.respond(s.syncFinishRecord, &spb.Response{
			ResponseType: &spb.Response_SyncResponse{
				SyncResponse: &spb.SyncResponse{
					Url: fmt.Sprintf("%s/%s/%s/runs/%s",
						s.settings.GetBaseURL(),
						s.settings.GetEntity(),
						s.settings.GetProject(),
						s.settings.GetRunID(),
					),
				},
			},
		})
	default:
		s.logger.Error(
			"sender: no sync finish record or exit record",
		)
	}

	// Prevent any new work from being added.
	//
	// Note that any work queued up at this point still gets processed.
	s.runWork.SetDone()
}

// flushWork waits until all work currently buffered is processed.
//
// It assumes mu is unlocked.
func (s *Sender) flushWork() {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.sentinelSent++
	sentinel := s.sentinelSent
	s.runWork.AddWork(runwork.NewSentinel(sentinel))

	// Wait until the sentinel we added is observed, which will happen after
	// all work that was queued when we added the sentinel is processed.
	for s.sentinelSeen < sentinel {
		s.sentinelCond.Wait()
	}
}

// observeSentinel updates the seen sentinel value based on work.Sentinel().
//
// mu must be held.
func (s *Sender) observeSentinel(work runwork.Work) {
	workSentinel := work.Sentinel()
	if workSentinel == nil {
		return
	}

	sentinel, ok := workSentinel.(senderSentinel)
	if !ok {
		return
	}

	if sentinel > s.sentinelSeen {
		s.sentinelSeen = sentinel
		s.sentinelCond.Broadcast()
	}
}

// finishFileStream waits for FileStream uploads to complete.
func (s *Sender) finishFileStream() {
	switch {
	case s.exitRecord != nil:
		s.fileStream.FinishWithExit(
			s.exitRecord.GetExit().GetExitCode(),
		)
	case s.finishWithoutExitRecord != nil:
		s.fileStream.FinishWithoutExit()
	default:
		s.logger.CaptureError(
			fmt.Errorf("sender: no exit code on finish"))
		s.fileStream.FinishWithoutExit()
	}
}

func (s *Sender) sendTelemetry(_ *spb.Record, telemetry *spb.TelemetryRecord) {
	proto.Merge(s.telemetry, telemetry)
	s.updateConfigPrivate()
	// TODO(perf): improve when debounce config is added, for now this sends all the time
	s.configDebouncer.SetNeedsDebounce()
}

func (s *Sender) sendPreempting(record *spb.RunPreemptingRecord) {
	if s.fileStream == nil {
		return
	}

	s.fileStream.StreamUpdate(&fs.PreemptingUpdate{Record: record})
}

func (s *Sender) sendLinkArtifact(record *spb.Record, msg *spb.LinkArtifactRequest) {
	var response spb.LinkArtifactResponse
	linker := artifacts.ArtifactLinker{
		Ctx:           s.runWork.BeforeEndCtx(),
		Logger:        s.logger,
		LinkArtifact:  msg,
		GraphqlClient: s.graphqlClient,
	}
	linkResponse, err := linker.Link()
	if err != nil {
		response.ErrorMessage = err.Error()
		s.logger.Error("sender: linkArtifact:", "error", err.Error())
	}

	if linkResponse != nil && linkResponse.LinkArtifact.VersionIndex != nil {
		v := int32(*linkResponse.LinkArtifact.VersionIndex)
		response.VersionIndex = &v
	} else {
		response.VersionIndex = nil
	}
	result := &spb.Result{
		ResultType: &spb.Result_Response{
			Response: &spb.Response{
				ResponseType: &spb.Response_LinkArtifactResponse{
					LinkArtifactResponse: &response,
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result
}

func (s *Sender) sendUseArtifact(record *spb.Record) {
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
func (s *Sender) serializeConfig(format runconfig.Format) ([]byte, error) {
	serializedConfig, err := s.runConfig.Serialize(format)

	if err != nil {
		err = fmt.Errorf("failed to marshal config: %s", err)
		s.logger.Error("sender: serializeConfig", "error", err)
		return nil, err
	}

	return serializedConfig, nil
}

// setConfigOnRunRecord sets the record's Config field to the current config.
func (s *Sender) setConfigOnRunRecord(record *spb.RunRecord) {
	record.Config = &spb.ConfigRecord{}

	for key, value := range s.runConfig.CloneTree() {
		valueJSON, _ := simplejsonext.MarshalToString(map[string]any{
			"value": value,
		})

		record.Config.Update = append(record.Config.Update,
			&spb.ConfigItem{
				Key:       key,
				ValueJson: valueJSON,
			})
	}
}

func (s *Sender) sendForkRun(record *spb.Record, run *spb.RunRecord) {
	fork := s.settings.GetForkFrom()
	err := runbranch.NewForkBranch(
		fork.GetRun(),
		fork.GetMetric(),
		fork.GetValue(),
	).UpdateForFork(s.startState)

	if err != nil {
		s.startState = nil

		s.logger.CaptureError(
			fmt.Errorf("send: sendRun: failed to update run state: %s", err),
		)

		// provide more info about the error to the user
		if errType, ok := err.(*runbranch.BranchError); ok {
			if errType.Response != nil {
				if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
					result := &spb.RunUpdateResult{
						Error: errType.Response,
					}
					s.respond(record, result)
				}
			}
		}

		return
	}

	s.upsertRun(record, run, true /*updateStartState*/)
}

func (s *Sender) sendRewindRun(record *spb.Record, run *spb.RunRecord) {
	// The client is nil if we're offline, in which case we cannot rewind.
	//
	// FIXME: This should return an error instead of silently doing nothing.
	if s.graphqlClient == nil {
		if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
			s.respond(record,
				&spb.RunUpdateResult{
					Run: run,
				},
			)
		}
		return
	}

	rewind := s.settings.GetResumeFrom()
	err := runbranch.NewRewindBranch(
		s.runWork.BeforeEndCtx(),
		s.graphqlClient,
		rewind.GetRun(),
		rewind.GetMetric(),
		rewind.GetValue(),
	).UpdateForRewind(s.startState, s.runConfig)

	if err != nil {
		s.startState = nil

		s.logger.Error(
			"send: sendRun: failed to update run state",
			"error", err,
		)

		// provide more info about the error to the user
		if errType, ok := err.(*runbranch.BranchError); ok {
			if errType.Response != nil {
				if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
					result := &spb.RunUpdateResult{
						Error: errType.Response,
					}
					s.respond(record, result)
				}
			}
		}

		return
	}

	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
		updatedRun := proto.CloneOf(run)
		s.startState.SetOnProto(updatedRun)
		s.setConfigOnRunRecord(updatedRun)
		s.respond(record, &spb.RunUpdateResult{Run: updatedRun})
	}
}

func (s *Sender) sendResumeRun(record *spb.Record, run *spb.RunRecord) {
	// The client is nil if we're offline, in which case we cannot resume.
	//
	// FIXME: This should return an error instead of silently doing nothing.
	if s.graphqlClient == nil {
		if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
			s.respond(record,
				&spb.RunUpdateResult{
					Run: run,
				},
			)
		}
		return
	}

	err := runbranch.NewResumeBranch(
		s.runWork.BeforeEndCtx(),
		s.graphqlClient,
		s.settings.GetResume(),
	).UpdateForResume(s.startState, s.runConfig)

	if err != nil {
		s.startState = nil

		s.logger.CaptureError(
			fmt.Errorf("send: sendRun: failed to update run state: %s", err),
		)

		// provide more info about the error to the user
		if errType, ok := err.(*runbranch.BranchError); ok {
			if errType.Response != nil {
				if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
					result := &spb.RunUpdateResult{
						Error: errType.Response,
					}
					s.respond(record, result)
				}
			}
		}

		return
	}

	updatedRun := proto.CloneOf(run)
	s.startState.SetOnProto(updatedRun)
	s.setConfigOnRunRecord(updatedRun)
	s.upsertRun(record, updatedRun, true /*updateStartState*/)
}

// sendRun sends a run record to the server and updates the run record
func (s *Sender) sendRun(record *spb.Record, run *spb.RunRecord) {
	// TODO: we use the same record type for the initial run upsert and the
	//  follow-up run updates, such as setting the name, tags, and notes.
	//  The client only expects a response for the initial upsert, the
	//  consequent updates are fire-and-forget and thus don't have a mailbox
	//  slot.
	//  We should probably separate the initial upsert from the updates.

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

	// If startState isn't nil, then we are updating an initialized run.
	if s.startState != nil {
		s.upsertRun(record, run, false /*updateStartState*/)
		return
	}

	s.startState = runbranch.NewRunParams(run, s.settings)

	isResume := s.settings.GetResume()
	isRewind := s.settings.GetResumeFrom()
	isFork := s.settings.GetForkFrom()
	switch {
	case isResume != "" && isRewind != nil || isResume != "" && isFork != nil || isRewind != nil && isFork != nil:
		if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
			s.respond(record,
				&spb.RunUpdateResult{
					Error: &spb.ErrorInfo{
						Code: spb.ErrorInfo_USAGE,
						Message: "`resume`, `fork_from`, and `resume_from` are mutually exclusive. " +
							"Please specify only one of them.",
					},
				},
			)
		}
		s.logger.Error("sender: sendRun: user provided more than one of resume, rewind, or fork")
	case isResume != "":
		s.sendResumeRun(record, run)
	case isRewind != nil:
		s.sendRewindRun(record, run)
	case isFork != nil:
		s.sendForkRun(record, run)
	default:
		s.upsertRun(record, run, true /*updateStartState*/)
	}
}

//gocyclo:ignore
func (s *Sender) upsertRun(
	record *spb.Record,
	run *spb.RunRecord,
	updateStartState bool,
) {
	// The client is nil if we're offline, in which case we cannot upsert.
	if s.graphqlClient == nil {
		if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
			s.respond(record,
				&spb.RunUpdateResult{
					Run: run,
				})
		}
		return
	}

	// start a new context with an additional argument from the parent context
	// this is used to pass the retry function to the graphql client
	ctx := context.WithValue(
		s.runWork.BeforeEndCtx(),
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)

	operation := s.operations.New("creating run")
	defer operation.Finish()
	ctx = operation.Context(ctx)

	// if the record has a mailbox slot, create a new cancelable context
	// and store the cancel function in the message registry so that
	// the context can be canceled if requested by the client
	mailboxSlot := record.GetControl().GetMailboxSlot()
	if mailboxSlot != "" {
		// if this times out, we mark the run as done as there is
		// no need to proceed with it
		ctx = s.mailbox.Add(ctx, s.runWork.SetDone, mailboxSlot)
	} else if updateStartState {
		// this should never happen:
		// the initial run upsert record should have a mailbox slot set by the client
		s.logger.CaptureFatalAndPanic(
			errors.New("sender: upsertRun: mailbox slot not set"),
		)
	}

	config, _ := s.serializeConfig(runconfig.FormatJson)
	configStr := string(config)

	var commit, repo string
	git := run.GetGit()
	if git != nil {
		commit = git.GetCommit()
		repo = git.GetRemoteUrl()
	}

	program := s.settings.GetProgram()

	var host string
	if !s.settings.IsDisableMachineInfo() {
		host = run.Host
	}

	data, err := gql.UpsertBucket(
		ctx,                                // ctx
		s.graphqlClient,                    // client
		nullify.NilIfZero(run.StorageId),   // id, required for auth checks when writing to a resumed run
		&run.RunId,                         // name
		nullify.NilIfZero(run.Project),     // project
		nullify.NilIfZero(run.Entity),      // entity
		nullify.NilIfZero(run.RunGroup),    // groupName
		nil,                                // description
		nullify.NilIfZero(run.DisplayName), // displayName
		nullify.NilIfZero(run.Notes),       // notes
		nullify.NilIfZero(commit),          // commit
		&configStr,                         // config
		nullify.NilIfZero(host),            // host
		nil,                                // debug
		nullify.NilIfZero(program),         // program
		nullify.NilIfZero(repo),            // repo
		nullify.NilIfZero(run.JobType),     // jobType
		nil,                                // state
		nullify.NilIfZero(run.SweepId),     // sweep
		run.Tags,                           // tags []string,
		nil,                                // summaryMetrics
	)

	if err != nil {
		err = fmt.Errorf("failed to upsert bucket: %s", err)
		s.logger.Error("sender: upsertRun:", "error", err)
		// TODO(sync): make this more robust in case of a failed UpsertBucket request.
		//  Need to inform the sync service that this ops failed.
		if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
			s.respond(record,
				&spb.RunUpdateResult{
					Error: &spb.ErrorInfo{
						Message: err.Error(),
						Code:    spb.ErrorInfo_COMMUNICATION,
					},
				},
			)
		}
		return
	}

	// manage the state of the run
	if data == nil || data.GetUpsertBucket() == nil || data.GetUpsertBucket().GetBucket() == nil {
		s.logger.Error("sender: upsertRun: upsert bucket response is empty")
	} else if updateStartState {
		// only update the state once on the initial run upsert, the subsequent
		// updates are fire-and-forget

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

		s.startState.FileStreamOffset[fs.HistoryChunk] = nullify.ZeroIfNil(
			bucket.GetHistoryLineCount(),
		)

		if storageID := bucket.GetId(); storageID != "" {
			s.startState.StorageID = storageID
		}
		if entityName != "" {
			s.startState.Entity = entityName
		}
		if projectName != "" {
			s.startState.Project = projectName
		}
		if runID := bucket.GetName(); runID != "" {
			s.startState.RunID = runID
		}
		if displayName := nullify.ZeroIfNil(bucket.GetDisplayName()); displayName != "" {
			s.startState.DisplayName = displayName
		}
		if sweepID := nullify.ZeroIfNil(bucket.GetSweepName()); sweepID != "" {
			s.startState.SweepID = sweepID
		}
	}

	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
		// This will be done only for the initial run upsert record
		// the consequent updates are fire-and-forget
		updatedRun := proto.CloneOf(run)
		s.startState.SetOnProto(updatedRun)
		s.respond(record, &spb.RunUpdateResult{Run: updatedRun})
	}
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(record *spb.HistoryRecord) {
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
		Record: &spb.SummaryRecord{Update: update},
	})
}

func (s *Sender) sendSummary(_ *spb.Record, summary *spb.SummaryRecord) {
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
	if s.startState == nil {
		s.logger.Error("sender: upsertConfig: RunRecord is nil")
		return
	}

	s.updateConfigPrivate()
	config, err := s.serializeConfig(runconfig.FormatJson)
	if err != nil {
		s.logger.Error("sender: upsertConfig: failed to serialize config", "error", err)
		return
	}
	if len(config) == 0 {
		return
	}
	configStr := string(config)

	ctx := context.WithValue(
		s.runWork.BeforeEndCtx(),
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)

	operation := s.operations.New("updating run config")
	defer operation.Finish()
	ctx = operation.Context(ctx)

	_, err = gql.UpsertBucket(
		ctx,                                     // ctx
		s.graphqlClient,                         // client
		nil,                                     // id
		&s.startState.RunID,                     // name
		nullify.NilIfZero(s.startState.Project), // project
		nullify.NilIfZero(s.startState.Entity),  // entity
		nil,                                     // groupName
		nil,                                     // description
		nil,                                     // displayName
		nil,                                     // notes
		nil,                                     // commit
		&configStr,                              // config
		nil,                                     // host
		nil,                                     // debug
		nil,                                     // program
		nil,                                     // repo
		nil,                                     // jobType
		nil,                                     // state
		nil,                                     // sweep
		nil,                                     // tags []string,
		nil,                                     // summaryMetrics
	)
	if err != nil {
		s.logger.Error("sender: sendConfig:", "error", err)
	}
}

func (s *Sender) uploadSummaryFile() {
	if s.runfilesUploader == nil {
		return
	}

	if s.startState == nil {
		return
	}

	if !s.settings.IsPrimary() {
		return
	}

	summary, err := s.runSummary.Serialize()
	if err != nil {
		s.logger.CaptureError(
			fmt.Errorf("sender: failed to serialize run summary: %v", err))
		return
	}

	if err := s.scheduleFileUpload(
		summary,
		SummaryFileName,
		filetransfer.RunFileKindWandb,
	); err != nil {
		s.logger.CaptureError(
			fmt.Errorf("sender: failed to upload run summary: %v", err))
	}
}

func (s *Sender) uploadConfigFile() {
	if s.runfilesUploader == nil {
		return
	}

	if s.startState == nil {
		return
	}

	if !s.settings.IsPrimary() {
		return
	}

	config, err := s.serializeConfig(runconfig.FormatYaml)
	if err != nil {
		s.logger.CaptureError(
			fmt.Errorf("sender: failed to serialize run config: %v", err))
		return
	}

	if err := s.scheduleFileUpload(
		config,
		ConfigFileName,
		filetransfer.RunFileKindWandb,
	); err != nil {
		s.logger.CaptureError(
			fmt.Errorf("sender: failed to upload run config: %v", err))
	}
}

// scheduleFileUpload creates and uploads a run file.
//
// The file is created in the run's files directory and uploaded
// asynchronously.
func (s *Sender) scheduleFileUpload(
	content []byte,
	runPathStr string,
	fileKind filetransfer.RunFileKind,
) error {
	if s.runfilesUploader == nil {
		return errors.New("runfilesUploader is nil")
	}

	maybeRunPath, err := paths.Relative(runPathStr)
	if err != nil {
		return err
	}
	runPath := *maybeRunPath

	if err = os.WriteFile(
		filepath.Join(
			s.settings.GetFilesDir(),
			string(runPath),
		),
		content,
		0644,
	); err != nil {
		return err
	}

	s.runfilesUploader.UploadNow(runPath, fileKind)
	return nil
}

// sendConfig sends a config record to the server via an upsertBucket mutation
// and updates the in memory config
func (s *Sender) sendConfig(_ *spb.Record, configRecord *spb.ConfigRecord) {
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
func (s *Sender) sendSystemMetrics(record *spb.StatsRecord) {
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

func (s *Sender) sendOutput(_ *spb.Record, _ *spb.OutputRecord) {
	// TODO: implement me
}

func (s *Sender) sendOutputRaw(_ *spb.Record, outputRaw *spb.OutputRawRecord) {
	s.consoleLogsSender.StreamLogs(outputRaw)
}

func (s *Sender) sendAlert(_ *spb.Record, alert *spb.AlertRecord) {
	if s.graphqlClient == nil {
		return
	}

	if s.startState == nil {
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

// sendRequestRunFinishWithoutExit triggers the shutdown of the stream without marking the run as finished
// on the server.
func (s *Sender) sendRequestRunFinishWithoutExit(record *spb.Record, _ *spb.RunFinishWithoutExitRequest) {
	if s.finishWithoutExitRecord != nil {
		s.logger.CaptureError(
			errors.New("sender: received RequestRunFinishWithoutExit more than once, ignoring"))
		return
	}

	s.finishWithoutExitRecord = record

	s.startFinishRun()
}

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(record *spb.Record) {
	if s.exitRecord != nil {
		s.logger.Warn("sender: received Exit record more than once, ignoring")
		return
	}

	// response is done by respond() and called when defer state machine is complete
	s.exitRecord = record

	s.startFinishRun()
}

// sendMetric updates the metrics in the run config.
func (s *Sender) sendMetric(record *spb.Record, _ *spb.MetricRecord) {
	// If server-side expand glob metrics is enabled, we don't need to send internal metrics
	// as these were expanded internally by the client.
	//
	// Note: we still send these metrics from the handler to the writer to ensure they are
	// available in the transaction log for offline runs that may be synced to a server that
	// does not support expanding glob metrics.
	if s.runConfigMetrics.IsServerExpandGlobMetrics() && record.GetMetric().GetExpandedFromGlob() {
		return
	}

	err := s.runConfigMetrics.ProcessRecord(record.GetMetric())

	if err != nil {
		s.logger.CaptureError(fmt.Errorf("sender: sendMetric: %v", err))
		return
	}

	s.configDebouncer.SetNeedsDebounce()
}

// sendFiles uploads files according to a FilesRecord
func (s *Sender) sendFiles(_ *spb.Record, filesRecord *spb.FilesRecord) {
	if s.runfilesUploader == nil {
		s.logger.CaptureWarn(
			"sender: tried to sendFiles, but runfiles uploader is nil",
		)
		return
	}

	s.runfilesUploader.Process(filesRecord)
}

func (s *Sender) sendArtifact(_ *spb.Record, msg *spb.ArtifactRecord) {
	op := s.operations.New(
		fmt.Sprintf(
			"uploading artifact %s",
			msg.Name))

	resultChan := s.artifactsSaver.Save(
		op.Context(s.runWork.BeforeEndCtx()),
		msg,
		0,
		"",
	)

	s.artifactWG.Add(1)
	go func() {
		defer s.artifactWG.Done()
		result := <-resultChan
		op.Finish()
		if result.Err != nil {
			s.logger.CaptureError(
				fmt.Errorf("sender: failed to log artifact: %v", result.Err),
				"artifactID", result.ArtifactID)
		}
	}()
}

func (s *Sender) sendRequestLogArtifact(record *spb.Record, msg *spb.LogArtifactRequest) {
	op := s.operations.New(
		fmt.Sprintf(
			"uploading artifact %s",
			msg.Artifact.Name))

	resultChan := s.artifactsSaver.Save(
		op.Context(s.runWork.BeforeEndCtx()),
		msg.Artifact,
		msg.HistoryStep,
		msg.StagingDir,
	)

	s.artifactWG.Add(1)
	go func() {
		defer s.artifactWG.Done()

		var response spb.LogArtifactResponse

		result := <-resultChan
		op.Finish()

		if result.Err != nil {
			response.ErrorMessage = result.Err.Error()
		} else {
			response.ArtifactId = result.ArtifactID
		}

		if msg.Artifact.GetType() == "code" {
			s.jobBuilder.SetRunCodeArtifact(
				response.ArtifactId,
				msg.Artifact.GetName(),
			)
		}

		s.respond(record,
			&spb.Response{
				ResponseType: &spb.Response_LogArtifactResponse{
					LogArtifactResponse: &response,
				},
			})
	}()
}

func (s *Sender) sendRequestDownloadArtifact(record *spb.Record, msg *spb.DownloadArtifactRequest) {
	var response spb.DownloadArtifactResponse

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
		&spb.Response{
			ResponseType: &spb.Response_DownloadArtifactResponse{
				DownloadArtifactResponse: &response,
			},
		})
}

func (s *Sender) sendRequestStopStatus(record *spb.Record, _ *spb.StopStatusRequest) {

	// TODO: unify everywhere to use settings
	entity := s.startState.Entity
	project := s.startState.Project
	runId := s.startState.RunID

	var stopResponse *spb.StopStatusResponse

	// if any of the entity, project or runId is empty, we can't make the request
	if entity == "" || project == "" || runId == "" {
		s.logger.Error("sender: sendStopStatus: entity, project, runId are empty")
		stopResponse = &spb.StopStatusResponse{
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
			stopResponse = &spb.StopStatusResponse{
				RunShouldStop: false,
			}
		case response == nil || response.GetProject() == nil || response.GetProject().GetRun() == nil:
			// if there is no response, we don't know if the run should stop
			stopResponse = &spb.StopStatusResponse{
				RunShouldStop: false,
			}
		default:
			stopped := nullify.ZeroIfNil(response.GetProject().GetRun().GetStopped())
			stopResponse = &spb.StopStatusResponse{
				RunShouldStop: stopped,
			}
		}
	}

	s.respond(record,
		&spb.Response{
			ResponseType: &spb.Response_StopStatusResponse{
				StopStatusResponse: stopResponse,
			},
		},
	)
}

func (s *Sender) sendRequestJobInput(request *spb.JobInputRequest) {
	if s.jobBuilder == nil {
		s.logger.Warn("sender: sendJobInput: job builder disabled, skipping")
		return
	}
	s.jobBuilder.HandleJobInputRequest(request)
}

func (s *Sender) sendRequestSyncFinish(record *spb.Record, _ *spb.SyncFinishRequest) {
	s.syncFinishRecord = record
}
