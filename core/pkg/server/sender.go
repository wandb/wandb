package server

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
        "strconv"
	"sync"
	"time"

        "crypto/sha256"
        "encoding/hex"
        "bytes"
	"image"
	"image/png"
	"image/color"
	"io/ioutil"

	"github.com/segmentio/encoding/json"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runresume"
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

func WithSenderMailbox(mailbox *mailbox.Mailbox) SenderOption {
	return func(s *Sender) {
		s.mailbox = mailbox
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
	fileStream fs.FileStream

	// filetransfer is the file uploader/downloader
	fileTransferManager filetransfer.FileTransferManager

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

	// debouncer for config updates
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

	networkPeeker *observability.Peeker

	mailbox *mailbox.Mailbox
}

// NewSender creates a new Sender with the given settings
func NewSender(
	ctx context.Context,
	cancel context.CancelFunc,
	backendOrNil *api.Backend,
	fileStreamOrNil fs.FileStream,
	fileTransferManagerOrNil filetransfer.FileTransferManager,
	logger *observability.CoreLogger,
	runfilesUploaderOrNil runfiles.Uploader,
	settings *service.Settings,
	peeker *observability.Peeker,
	graphqlClient graphql.Client,
	opts ...SenderOption,
) *Sender {

	sender := &Sender{
		ctx:                 ctx,
		cancel:              cancel,
		settings:            settings,
		logger:              logger,
		summaryMap:          make(map[string]*service.SummaryItem),
		runConfig:           runconfig.New(),
		telemetry:           &service.TelemetryRecord{CoreVersion: version.Version},
		wgFileTransfer:      sync.WaitGroup{},
		fileStream:          fileStreamOrNil,
		fileTransferManager: fileTransferManagerOrNil,
		runfilesUploader:    runfilesUploaderOrNil,
		networkPeeker:       peeker,
		graphqlClient:       graphqlClient,
	}

	if !settings.GetXOffline().GetValue() && backendOrNil != nil && !settings.GetDisableJobCreation().GetValue() {
		sender.jobBuilder = launch.NewJobBuilder(settings, logger, false)
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
		s.logger.Debug(
			"sender: processing record",
			"record", record.RecordType,
			"stream_id", s.settings.RunId,
		)
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
		s.sendHistory(record, x.History)
	case *service.Record_Summary:
		s.sendSummary(record, x.Summary)
	case *service.Record_Config:
		s.sendConfig(record, x.Config)
	case *service.Record_Stats:
		s.sendSystemMetrics(record, x.Stats)
	case *service.Record_OutputRaw:
		s.sendOutputRaw(record, x.OutputRaw)
	case *service.Record_Output:
		s.sendOutput(record, x.Output)
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

	fsPath := fmt.Sprintf(
		"files/%s/%s/%s/file_stream",
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
	)

	if s.fileStream != nil {
		s.fileStream.SetPath(fsPath)
		s.fileStream.SetOffsets(s.resumeState.GetFileStreamOffset())
		s.fileStream.Start()
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
		result := &service.Result{
			ResultType: &service.Result_Response{
				Response: &service.Response{
					ResponseType: &service.Response_NetworkStatusResponse{
						NetworkStatusResponse: &service.NetworkStatusResponse{
							NetworkResponses: response,
						},
					},
				},
			},
			Control: record.Control,
			Uuid:    record.Uuid,
		}
		s.outChan <- result
	}
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
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_DEBOUNCER:
		s.configDebouncer.Flush(s.upsertConfig)
		s.writeAndSendConfigFile()
		request.State++
		s.fwdRequestDefer(request)
	case service.DeferRequest_FLUSH_OUTPUT:
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
		s.respondExit(s.exitRecord)
		// cancel tells the stream to close the loopback channel
		s.cancel()
	default:
		err := fmt.Errorf("sender: sendDefer: unexpected state %v", request.State)
		s.logger.CaptureFatalAndPanic("sender: sendDefer: unexpected state", err)
	}
}

func (s *Sender) fwdRequestDefer(request *service.DeferRequest) {
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
	if s.fileStream == nil {
		return
	}

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

func createPNG(data []byte, width, height int, filesPath string, imagePath string) (string, string, int, error) {
	// Create a new RGBA image
	img := image.NewRGBA(image.Rect(0, 0, width, height))

	// Index for accessing the byte array
	idx := 0

	// Populate the image with pixels
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			r := data[idx]
			g := data[idx+1]
			b := data[idx+2]
			img.SetRGBA(x, y, color.RGBA{R: r, G: g, B: b, A: 0xff})
			idx += 3 // Move to the next pixel (skip 3 bytes)
		}
	}

	// Create a buffer to write our PNG to
	var buf bytes.Buffer

	// Encode the image to the buffer
	if err := png.Encode(&buf, img); err != nil {
		return "", "", 0, err
	}

        // Compute SHA256 of the buffer
        hasher := sha256.New()
        hasher.Write(buf.Bytes())
        hash := hex.EncodeToString(hasher.Sum(nil))

        // Compute file size
        size := buf.Len()

        imagePath = fmt.Sprintf("%s_%s.png", imagePath, hash[:20])
	outputPath := filepath.Join(filesPath, imagePath)

        // Ensure all directories exist
        dirPath := filepath.Dir(outputPath)
        if err := os.MkdirAll(dirPath, 0755); err != nil {
                return "", "", 0, err
        }

	// Write the buffer to a file
	if err := ioutil.WriteFile(outputPath, buf.Bytes(), 0644); err != nil {
		return "", "", 0, err
	}

	return imagePath, hash, size, nil
}

/*
_type:"image-file"
format:"png"
height:8
path:"media/images/e_0_bf803d096a43bb99af79.png"
sha256:"bf803d096a43bb99af79738cfc7e036f5021727042a67ff3c99a0cd114c49cad"
size:268
width:8
*/
type Media struct {
        Type string `json:"_type"`
        Format string `json:"format"`
        Height int `json:"height"`
        Width int `json:"width"`
        Path string `json:"path"`
        Sha256 string `json:"sha256"`
        Size int `json:"size"`
}

// might want to move this info filestream... ideally we should do something like this:
//   process during sendHistory,  schedule work to be done for the history data especially the media
//   then at filestream process time / or fs transmit time, do final step coallescing data, for example
//   it might be cool to sprite multiple steps of the same image key. kinda tricky to do
func historyMediaProcess(hrecord *service.HistoryRecord, filesPath string) (*service.HistoryRecord, []string) {
        hrecordNew := &service.HistoryRecord{
                Step: hrecord.Step,
        }
        hFiles := []string{}
	for _, item := range hrecord.Item {
                if item.ValueData != nil {
                        hItem := &service.HistoryItem{Key: item.Key}
                        switch value := item.ValueData.DataType.(type) {
                                case *service.DataValue_ValueInt:
                                        hItem.ValueJson = strconv.FormatInt(value.ValueInt, 10)
                                case *service.DataValue_ValueDouble:
                                        hItem.ValueJson = strconv.FormatFloat(value.ValueDouble, 'E', -1, 64)
                                case *service.DataValue_ValueString:
                                        hItem.ValueJson = fmt.Sprintf(`"%s"`, value.ValueString)
                                case *service.DataValue_ValueTensor:
                                        // fmt.Printf("GOT TENSOR %+v\n", value.ValueTensor)
                                        imageBase := fmt.Sprintf("%s_%d", item.Key, hrecord.Step.Num)
	                                imagePath := filepath.Join("media", "images", imageBase)
                                        shape := value.ValueTensor.Shape
                                        height := int(shape[0])
                                        width := int(shape[1])
                                        // FIXME: make sure channels is 3 for now
                                        // FIXME: we only handle dtype uint8 also
                                        fname, hash, size, err := createPNG(value.ValueTensor.TensorContent, height, width, filesPath, imagePath)
                                        if err != nil {
                                                fmt.Printf("GOT err %+v\n", err)
                                        }
                                        hFiles = append(hFiles, fname)
                                        media := Media{
                                                Type: "image-file",
                                                Format: "png",
                                                Height: height,
                                                Width: width,
                                                Size: size,
                                                Sha256: hash,
                                                Path: fname,
                                        }
                                        jsonString, err := json.Marshal(media)
                                        if err != nil {
                                                fmt.Printf("GOT err %+v\n", err)
                                        }
                                        // fmt.Printf("GOT::: %+v %+v %+v %+v\n", string(jsonString), fname, hash, size)
                                        hItem.ValueJson = string(jsonString)
                        }
		        hrecordNew.Item = append(hrecordNew.Item, hItem)
                } else {
		        hrecordNew.Item = append(hrecordNew.Item, item)
                }
        }
        return hrecordNew, hFiles
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(record *service.Record, hrecord *service.HistoryRecord) {
	if s.fileStream == nil {
		return
	}
        filesPath := s.settings.GetFilesDir().GetValue()
        hrecordNew, hFileNames := historyMediaProcess(hrecord, filesPath)
        if s.runfilesUploader == nil {
                return
        }
        for _, hfile := range hFileNames{
            // fmt.Printf("hfile: %+v\n", hfile)
            filesRecord := &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: hfile,
						Type: service.FilesItem_MEDIA,
					},
				},
                        }
	    s.runfilesUploader.Process(filesRecord)
        }
        // TODO: do this better?
        recordNew := &service.Record{
                RecordType: &service.Record_History{
                        History: hrecordNew,
                },
                Control: record.Control,
                Uuid: record.Uuid,
        }

	s.fileStream.StreamRecord(recordNew)
}

func (s *Sender) sendSummary(_ *service.Record, summary *service.SummaryRecord) {

	// TODO(network): buffer summary sending for network efficiency until we can send only updates
	// TODO(compat): handle deletes, nested keys
	// TODO(compat): write summary file

	// track each key in the in memory summary store
	// TODO(memory): avoid keeping summary for all distinct keys
	for _, item := range summary.Update {
                // TODO: this isnt really right.. could be an empty string, want to deal with Data values
                if item.ValueJson == "" {
                        continue
                }
	 	s.summaryMap[item.Key] = item
	}

	if s.fileStream != nil {
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
	if s.fileStream == nil {
		return
	}

	s.fileStream.StreamRecord(record)
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

func (s *Sender) sendOutputRaw(record *service.Record, outputRaw *service.OutputRawRecord) {
	// TODO: match logic handling of lines to the one in the python version
	// - handle carriage returns (for tqdm-like progress bars)
	// - handle caching multiple (non-new lines) and sending them in one chunk
	// - handle lines longer than ~60_000 characters

	// ignore empty "new lines"
	if outputRaw.Line == "\n" {
		return
	}

	outputFile := filepath.Join(s.settings.GetFilesDir().GetValue(), OutputFileName)
	// append line to file
	if err := writeOutputToFile(outputFile, outputRaw.Line); err != nil {
		s.logger.Error("sender: sendOutput: failed to write to output file", "error", err)
	}

	if s.fileStream == nil {
		return
	}

	// generate compatible timestamp to python iso-format (microseconds without Z)
	t := strings.TrimSuffix(time.Now().UTC().Format(RFC3339Micro), "Z")
	var line string
	switch outputRaw.OutputType {
	case service.OutputRawRecord_STDOUT:
		line = fmt.Sprintf("%s %s", t, outputRaw.Line)
	case service.OutputRawRecord_STDERR:
		line = fmt.Sprintf("ERROR %s %s", t, outputRaw.Line)
	default:
		err := fmt.Errorf("sender: sendOutputRaw: unexpected output type %v", outputRaw.OutputType)
		s.logger.CaptureError("sender received error", err)
		return
	}
	newRecord := &service.Record{
		RecordType: &service.Record_OutputRaw{
			OutputRaw: &service.OutputRawRecord{
				Line: line,
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
		XInfo:   record.XInfo,
	}
	s.fileStream.StreamRecord(newRecord)
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

	if s.fileStream != nil {
		s.fileStream.StreamRecord(record)
	}

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
		s.ctx, s.graphqlClient, s.fileTransferManager, msg, 0, "",
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

func (s *Sender) sendRequestDownloadArtifact(record *service.Record, msg *service.DownloadArtifactRequest) {
	// TODO: this should be handled by a separate service starup mechanism
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
		// if there is an error, we don't know if the run should stop
		if err != nil {
			err = fmt.Errorf("sender: sendStopStatus: failed to get run stopped status: %s", err)
			s.logger.CaptureError("sender received error", err)
			stopResponse = &service.StopStatusResponse{
				RunShouldStop: false,
			}
		} else {
			stopped := utils.ZeroIfNil(response.GetProject().GetRun().GetStopped())
			stopResponse = &service.StopStatusResponse{
				RunShouldStop: stopped,
			}
		}
	}

	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_StopStatusResponse{
					StopStatusResponse: stopResponse,
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}

	s.outChan <- result
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

func (s *Sender) sendRequestJobInput(request *service.JobInputRequest) {
	if s.jobBuilder == nil {
		s.logger.Warn("sender: sendJobInput: job builder disabled, skipping")
		return
	}
	s.jobBuilder.HandleJobInputRequest(request)
}
