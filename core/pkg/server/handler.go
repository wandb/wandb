package server

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/utils"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/timer"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/observability"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	MetaFileName         = "wandb-metadata.json"
	SummaryFileName      = "wandb-summary.json"
	DiffFileName         = "diff.patch"
	RequirementsFileName = "requirements.txt"
	ConfigFileName       = "config.yaml"
	LatestOutputFileName = "output.log"
)

type HandlerParams struct {
	Settings          *spb.Settings
	FwdChan           chan *spb.Record
	OutChan           chan *spb.Result
	Logger            *observability.CoreLogger
	Mailbox           *mailbox.Mailbox
	FileTransferStats filetransfer.FileTransferStats
	RunfilesUploader  runfiles.Uploader
	TBHandler         *tensorboard.TBHandler
	SystemMonitor     *monitor.SystemMonitor
	TerminalPrinter   *observability.Printer

	// SkipSummary controls whether to skip summary updates.
	//
	// This is only useful in a test.
	SkipSummary bool
}

// Handler is the handler for a stream it handles the incoming messages, processes them
// and passes them to the writer
type Handler struct {
	// commit is the W&B Git commit hash
	commit string

	// settings is the settings for the handler
	settings *spb.Settings

	// clientID is an ID for this process.
	//
	// This identifies the process that uploaded a set of metrics when
	// running in "shared" mode, where there may be multiple writers for
	// the same run.
	clientID string

	// logger is the logger for the handler
	logger *observability.CoreLogger

	// fwdChan is the channel for forwarding messages to the next component
	fwdChan chan *spb.Record

	// outChan is the channel for sending results to the client
	outChan chan *spb.Result

	// runTimer is used to track the run start and execution times
	runTimer *timer.Timer

	// runRecord is the runRecord record received from the server
	runRecord *spb.RunRecord

	// partialHistory is a set of run metrics accumulated for the current step.
	partialHistory *runhistory.RunHistory

	// partialHistoryStep is the next history "step" to emit
	// when not running in shared mode.
	partialHistoryStep int64

	// runHistorySampler tracks samples of all metrics in the run's history.
	//
	// This is used to display the sparkline in the terminal at the end of
	// the run.
	runHistorySampler *runhistory.RunHistorySampler

	// metricHandler is the metric handler for the stream
	metricHandler *runmetric.MetricHandler

	// runSummary contains summaries of the run's metrics.
	//
	// These summaries are up-to-date with respect to the current request being
	// handled which is crucial for serving the GetSummaryRequest. The Sender
	// also tracks summaries, but with respect to its own queue of requests,
	// which may be arbitrarily far behind the Handler.
	runSummary *runsummary.RunSummary

	// skipSummary is set in tests where certain summary records should be
	// ignored.
	skipSummary bool

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor

	// metadata stores the run metadata including system stats
	metadata *spb.MetadataRequest

	// tbHandler is the tensorboard handler
	tbHandler *tensorboard.TBHandler

	// runfilesUploaderOrNil manages uploading a run's files
	//
	// It may be nil when offline.
	// TODO: should this be moved to the sender?
	runfilesUploaderOrNil runfiles.Uploader

	// fileTransferStats reports file upload/download statistics
	fileTransferStats filetransfer.FileTransferStats

	// terminalPrinter gathers terminal messages to send back to the user process
	terminalPrinter *observability.Printer

	mailbox *mailbox.Mailbox
}

// NewHandler creates a new handler
func NewHandler(
	commit string,
	params HandlerParams,
) *Handler {
	return &Handler{
		commit:                commit,
		runTimer:              timer.New(),
		terminalPrinter:       params.TerminalPrinter,
		logger:                params.Logger,
		settings:              params.Settings,
		clientID:              utils.ShortID(32),
		fwdChan:               params.FwdChan,
		outChan:               params.OutChan,
		mailbox:               params.Mailbox,
		runSummary:            runsummary.New(),
		skipSummary:           params.SkipSummary,
		runHistorySampler:     runhistory.NewRunHistorySampler(),
		metricHandler:         runmetric.New(),
		fileTransferStats:     params.FileTransferStats,
		runfilesUploaderOrNil: params.RunfilesUploader,
		tbHandler:             params.TBHandler,
		systemMonitor:         params.SystemMonitor,
	}
}

// Do processes all records on the input channel.
func (h *Handler) Do(inChan <-chan *spb.Record) {
	defer h.logger.Reraise()
	h.logger.Info("handler: started", "stream_id", h.settings.RunId)
	for record := range inChan {
		h.logger.Debug("handle: got a message", "record_type", record.RecordType, "stream_id", h.settings.RunId)
		h.handleRecord(record)
	}
	h.Close()
}

func (h *Handler) Close() {
	close(h.outChan)
	close(h.fwdChan)
	h.logger.Info("handler: closed", "stream_id", h.settings.RunId)
}

// respond sends a response to the client
func (h *Handler) respond(record *spb.Record, response *spb.Response) {
	result := &spb.Result{
		ResultType: &spb.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.outChan <- result
}

// fwdRecord forwards a record to the next component
func (h *Handler) fwdRecord(record *spb.Record) {
	if record == nil {
		return
	}
	h.fwdChan <- record
}

// fwdRecordWithControl forwards a record to the next component with control options
func (h *Handler) fwdRecordWithControl(record *spb.Record, controlOptions ...func(*spb.Control)) {
	if record == nil {
		return
	}

	if record.GetControl() == nil {
		record.Control = &spb.Control{}
	}

	for _, opt := range controlOptions {
		opt(record.Control)
	}
	h.fwdRecord(record)
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *spb.Record) {
	switch x := record.RecordType.(type) {
	case *spb.Record_Alert:
		h.handleAlert(record)
	case *spb.Record_Artifact:
		h.handleArtifact(record)
	case *spb.Record_Config:
		h.handleConfig(record)
	case *spb.Record_Exit:
		h.handleExit(record, x.Exit)
	case *spb.Record_Files:
		h.handleFiles(record)
	case *spb.Record_Final:
		h.handleFinal()
	case *spb.Record_Footer:
		h.handleFooter()
	case *spb.Record_Header:
		h.handleHeader(record)
	case *spb.Record_History:
		h.handleHistoryDirectly(x.History)
	case *spb.Record_NoopLinkArtifact:
		// Removed but kept to avoid panics
	case *spb.Record_Metric:
		h.handleMetric(record)
	case *spb.Record_Output:
		h.handleOutput(record)
	case *spb.Record_OutputRaw:
		h.handleOutputRaw(record)
	case *spb.Record_Preempting:
		h.handlePreempting(record)
	case *spb.Record_Request:
		h.handleRequest(record)
	case *spb.Record_Run:
		h.handleRun(record)
	case *spb.Record_Stats:
		h.handleSystemMetrics(record)
	case *spb.Record_Summary:
		h.handleSummary(record, x.Summary)
	case *spb.Record_Tbrecord:
		h.handleTBrecord(x.Tbrecord)
	case *spb.Record_Telemetry:
		h.handleTelemetry(record)
	case *spb.Record_UseArtifact:
		h.handleUseArtifact(record)
	case nil:
		h.logger.CaptureFatalAndPanic(
			errors.New("handler: handleRecord: record type is nil"))
	default:
		h.logger.CaptureFatalAndPanic(
			fmt.Errorf("handler: handleRecord: unknown record type %T", x))
	}
}

//gocyclo:ignore
func (h *Handler) handleRequest(record *spb.Record) {
	request := record.GetRequest()
	switch x := request.RequestType.(type) {
	case *spb.Request_Login:
		h.handleRequestLogin(record)
	case *spb.Request_CheckVersion:
		h.handleRequestCheckVersion(record)
	case *spb.Request_RunStatus:
		h.handleRequestRunStatus(record)
	case *spb.Request_Metadata:
		h.handleMetadata(x.Metadata)
	case *spb.Request_SummaryRecord:
		// TODO: handles sending summary file
	case *spb.Request_TelemetryRecord:
		// TODO: handles sending telemetry record
	case *spb.Request_TestInject:
		// not implemented in the old handler
	case *spb.Request_JobInfo:
		// not implemented in the old handler
	case *spb.Request_Status:
		h.handleRequestStatus(record)
	case *spb.Request_SenderMark:
		h.handleRequestSenderMark(record)
	case *spb.Request_StatusReport:
		h.handleRequestStatusReport(record)
	case *spb.Request_Keepalive:
		// keepalive is a no-op
	case *spb.Request_Shutdown:
		h.handleRequestShutdown(record)
	case *spb.Request_Defer:
		h.handleRequestDefer(record, x.Defer)
	case *spb.Request_GetSummary:
		h.handleRequestGetSummary(record)
	case *spb.Request_NetworkStatus:
		h.handleRequestNetworkStatus(record)
	case *spb.Request_PartialHistory:
		h.handleRequestPartialHistory(record, x.PartialHistory)
	case *spb.Request_PollExit:
		h.handleRequestPollExit(record)
	case *spb.Request_RunStart:
		h.handleRequestRunStart(record, x.RunStart)
	case *spb.Request_SampledHistory:
		h.handleRequestSampledHistory(record)
	case *spb.Request_ServerInfo:
		h.handleRequestServerInfo(record)
	case *spb.Request_PythonPackages:
		h.handleRequestPythonPackages(record, x.PythonPackages)
	case *spb.Request_StopStatus:
		h.handleRequestStopStatus(record)
	case *spb.Request_LogArtifact:
		h.handleRequestLogArtifact(record)
	case *spb.Request_LinkArtifact:
		h.handleRequestLinkArtifact(record)
	case *spb.Request_DownloadArtifact:
		h.handleRequestDownloadArtifact(record)
	case *spb.Request_Attach:
		h.handleRequestAttach(record)
	case *spb.Request_Pause:
		h.handleRequestPause()
	case *spb.Request_Resume:
		h.handleRequestResume()
	case *spb.Request_Cancel:
		h.handleRequestCancel(x.Cancel)
	case *spb.Request_GetSystemMetrics:
		h.handleRequestGetSystemMetrics(record)
	case *spb.Request_InternalMessages:
		h.handleRequestInternalMessages(record)
	case *spb.Request_Sync:
		h.handleRequestSync(record)
	case *spb.Request_SenderRead:
		h.handleRequestSenderRead(record)
	case *spb.Request_JobInput:
		h.handleRequestJobInput(record)
	case nil:
		h.logger.CaptureFatalAndPanic(
			errors.New("handler: handleRequest: request type is nil"))
	default:
		h.logger.CaptureFatalAndPanic(
			fmt.Errorf("handler: handleRequest: unknown request type %T", x))
	}
}

func (h *Handler) handleRequestLogin(record *spb.Record) {
	// TODO: implement login if it is needed
	if record.GetControl().GetReqResp() {
		h.respond(record, &spb.Response{})
	}
}

func (h *Handler) handleRequestCheckVersion(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestRunStatus(record *spb.Record) {
	// TODO(flow-control): implement run status
	h.respond(record, &spb.Response{})
}

func (h *Handler) handleRequestStatus(record *spb.Record) {
	h.respond(record, &spb.Response{})
}

func (h *Handler) handleRequestSenderMark(_ *spb.Record) {
	// TODO(flow-control): implement sender mark
}

func (h *Handler) handleRequestStatusReport(_ *spb.Record) {
	// TODO(flow-control): implement status report
}

func (h *Handler) handleRequestShutdown(record *spb.Record) {
	h.respond(record, &spb.Response{})
}

func (h *Handler) handleMetric(record *spb.Record) {
	metric := record.GetMetric()
	if metric == nil {
		h.logger.CaptureError(
			errors.New("handler: bad record type for handleMetric"))
		return
	}

	if err := h.metricHandler.ProcessRecord(metric); err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: cannot add metric: %v", err),
			"metric", metric)
		return
	}

	if len(metric.Name) > 0 {
		h.metricHandler.UpdateSummary(metric.Name, h.runSummary)
	}

	h.fwdRecord(record)
}

func (h *Handler) handleRequestDefer(record *spb.Record, request *spb.DeferRequest) {
	switch request.State {
	case spb.DeferRequest_BEGIN:
	case spb.DeferRequest_FLUSH_RUN:
	case spb.DeferRequest_FLUSH_STATS:
		// stop the system monitor to ensure that we don't send any more system metrics
		// after the run has exited
		h.systemMonitor.Finish()
	case spb.DeferRequest_FLUSH_PARTIAL_HISTORY:
		// This will force the content of h.runHistory to be flushed and sent
		// over to the sender.
		//
		// Since the data of the PartialHistoryRequest is empty it will not
		// change the content of h.runHistory, but it will trigger flushing
		// of h.runHistory content, because the flush action is set to true.
		// Hence, we are guranteed that the content of h.runHistory is sent
		h.handleRequestPartialHistory(
			nil,
			&spb.PartialHistoryRequest{
				Action: &spb.HistoryAction{
					Flush: true,
				},
			},
		)
	case spb.DeferRequest_FLUSH_TB:
	case spb.DeferRequest_FLUSH_SUM:
	case spb.DeferRequest_FLUSH_DEBOUNCER:
	case spb.DeferRequest_FLUSH_OUTPUT:
	case spb.DeferRequest_FLUSH_JOB:
	case spb.DeferRequest_FLUSH_DIR:
	case spb.DeferRequest_FLUSH_FP:
		if h.runfilesUploaderOrNil != nil {
			h.runfilesUploaderOrNil.UploadRemaining()
		}
	case spb.DeferRequest_JOIN_FP:
	case spb.DeferRequest_FLUSH_FS:
	case spb.DeferRequest_FLUSH_FINAL:
		h.handleFinal()
		h.handleFooter()
	case spb.DeferRequest_END:
		h.fileTransferStats.SetDone()
	default:
		h.logger.CaptureError(
			fmt.Errorf("handleDefer: unknown defer state %v", request.State))
	}
	// Need to clone the record to avoid race condition with the writer
	record = proto.Clone(record).(*spb.Record)
	h.fwdRecordWithControl(record,
		func(control *spb.Control) {
			control.AlwaysSend = true
		},
		func(control *spb.Control) {
			control.Local = true
		},
	)
}

func (h *Handler) handleRequestStopStatus(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleArtifact(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestLogArtifact(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestDownloadArtifact(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestLinkArtifact(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestPollExit(record *spb.Record) {
	var pollExitResponse *spb.PollExitResponse
	if h.fileTransferStats != nil {
		pollExitResponse = &spb.PollExitResponse{
			PusherStats: h.fileTransferStats.GetFilesStats(),
			FileCounts:  h.fileTransferStats.GetFileCounts(),
			Done:        h.fileTransferStats.IsDone(),
		}
	} else {
		pollExitResponse = &spb.PollExitResponse{
			Done: true,
		}
	}

	response := &spb.Response{
		ResponseType: &spb.Response_PollExitResponse{
			PollExitResponse: pollExitResponse,
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleHeader(record *spb.Record) {
	// populate with version info
	versionString := fmt.Sprintf("%s+%s", version.Version, h.commit)
	record.GetHeader().VersionInfo = &spb.VersionInfo{
		Producer:    versionString,
		MinConsumer: version.MinServerVersion,
	}
	h.fwdRecordWithControl(
		record,
		func(control *spb.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleFinal() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}
	record := &spb.Record{
		RecordType: &spb.Record_Final{
			Final: &spb.FinalRecord{},
		},
	}
	h.fwdRecordWithControl(
		record,
		func(control *spb.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleFooter() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}
	record := &spb.Record{
		RecordType: &spb.Record_Footer{
			Footer: &spb.FooterRecord{},
		},
	}
	h.fwdRecordWithControl(
		record,
		func(control *spb.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleRequestServerInfo(record *spb.Record) {
	h.fwdRecordWithControl(record,
		func(control *spb.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleRequestRunStart(record *spb.Record, request *spb.RunStartRequest) {
	var ok bool
	run := request.Run

	// offsset by run.Runtime to account for potential run branching
	startTime := run.StartTime.AsTime().Add(time.Duration(-run.Runtime) * time.Second)
	// start the run timer
	h.runTimer.Start(&startTime)

	if h.runRecord, ok = proto.Clone(run).(*spb.RunRecord); !ok {
		h.logger.CaptureFatalAndPanic(
			errors.New("handleRunStart: failed to clone run"))
	}
	h.fwdRecord(record)
	// NOTE: once this request arrives in the sender,
	// the latter will start its filestream and uploader

	// initialize the run metadata from settings
	var git *spb.GitRepoRecord
	if run.GetGit().GetRemoteUrl() != "" || run.GetGit().GetCommit() != "" {
		git = &spb.GitRepoRecord{
			RemoteUrl: run.GetGit().GetRemoteUrl(),
			Commit:    run.GetGit().GetCommit(),
		}
	}

	metadata := &spb.MetadataRequest{
		Os:            h.settings.GetXOs().GetValue(),
		Python:        h.settings.GetXPython().GetValue(),
		Host:          h.settings.GetHost().GetValue(),
		Cuda:          h.settings.GetXCuda().GetValue(),
		Program:       h.settings.GetProgram().GetValue(),
		CodePath:      h.settings.GetProgramRelpath().GetValue(),
		CodePathLocal: h.settings.GetXCodePathLocal().GetValue(),
		Email:         h.settings.GetEmail().GetValue(),
		Root:          h.settings.GetRootDir().GetValue(),
		Username:      h.settings.GetUsername().GetValue(),
		Docker:        h.settings.GetDocker().GetValue(),
		Executable:    h.settings.GetXExecutable().GetValue(),
		Args:          h.settings.GetXArgs().GetValue(),
		Colab:         h.settings.GetColabUrl().GetValue(),
		StartedAt:     run.GetStartTime(),
		Git:           git,
	}
	h.handleMetadata(metadata)

	// start the system monitor
	if !h.settings.GetXDisableStats().GetValue() {
		h.systemMonitor.Start()
	}

	// save code and patch
	if h.settings.GetSaveCode().GetValue() {
		h.handleCodeSave()
		h.handlePatchSave()
	}

	h.respond(record, &spb.Response{})
}

func (h *Handler) handleRequestPythonPackages(_ *spb.Record, request *spb.PythonPackagesRequest) {
	// write all requirements to a file
	// send the file as a Files record
	filename := filepath.Join(h.settings.GetFilesDir().GetValue(), RequirementsFileName)
	file, err := os.Create(filename)
	if err != nil {
		h.logger.Error("error creating requirements file", "error", err)
		return
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			h.logger.Error("error closing requirements file", "error", err)
		}
	}(file)

	for _, pkg := range request.Package {
		line := fmt.Sprintf("%s==%s\n", pkg.Name, pkg.Version)
		_, err := file.WriteString(line)
		if err != nil {
			h.logger.Error("error writing requirements file", "error", err)
			return
		}
	}
	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: []*spb.FilesItem{
					{
						Path: RequirementsFileName,
						Type: spb.FilesItem_WANDB,
					},
				},
			},
		},
	}
	h.handleFiles(record)
}

func (h *Handler) handleCodeSave() {
	programRelative := h.settings.GetProgramRelpath().GetValue()
	if programRelative == "" {
		h.logger.Warn("handleCodeSave: program relative path is empty")
		return
	}

	programAbsolute := h.settings.GetProgramAbspath().GetValue()
	if _, err := os.Stat(programAbsolute); err != nil {
		h.logger.Warn("handleCodeSave: program absolute path does not exist", "path", programAbsolute)
		return
	}

	codeDir := filepath.Join(h.settings.GetFilesDir().GetValue(), "code")
	if err := os.MkdirAll(filepath.Join(codeDir, filepath.Dir(programRelative)), os.ModePerm); err != nil {
		return
	}
	savedProgram := filepath.Join(codeDir, programRelative)
	if _, err := os.Stat(savedProgram); err != nil {
		if err = utils.CopyFile(programAbsolute, savedProgram); err != nil {
			return
		}
	}
	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: []*spb.FilesItem{
					{
						Path: filepath.Join("code", programRelative),
						Type: spb.FilesItem_WANDB,
					},
				},
			},
		},
	}
	h.handleFiles(record)
}

func (h *Handler) handlePatchSave() {
	// capture git state
	if h.settings.GetDisableGit().GetValue() {
		return
	}

	git := NewGit(h.settings.GetRootDir().GetValue(), h.logger)
	if !git.IsAvailable() {
		return
	}

	var files []*spb.FilesItem

	filesDirPath := h.settings.GetFilesDir().GetValue()
	file := filepath.Join(filesDirPath, DiffFileName)
	if err := git.SavePatch("HEAD", file); err != nil {
		h.logger.Error("error generating diff", "error", err)
	} else {
		files = append(files, &spb.FilesItem{Path: DiffFileName, Type: spb.FilesItem_WANDB})
	}

	if output, err := git.LatestCommit("@{u}"); err != nil {
		h.logger.Error("error getting latest commit", "error", err)
	} else {
		diffFileName := fmt.Sprintf("diff_%s.patch", output)
		file = filepath.Join(filesDirPath, diffFileName)
		if err := git.SavePatch("@{u}", file); err != nil {
			h.logger.Error("error generating diff", "error", err)
		} else {
			files = append(files, &spb.FilesItem{Path: diffFileName, Type: spb.FilesItem_WANDB})
		}
	}

	if len(files) == 0 {
		return
	}

	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: files,
			},
		},
	}
	h.handleFiles(record)
}

func (h *Handler) handleMetadata(request *spb.MetadataRequest) {
	// TODO: Sending metadata as a request for now, eventually this should be turned into
	//  a record and stored in the transaction log
	if h.settings.GetXDisableMeta().GetValue() {
		return
	}

	if h.metadata == nil {
		h.metadata = proto.Clone(request).(*spb.MetadataRequest)
	} else {
		proto.Merge(h.metadata, request)
	}

	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, err := mo.Marshal(h.metadata)
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("error marshalling metadata: %v", err))
		return
	}
	filePath := filepath.Join(h.settings.GetFilesDir().GetValue(), MetaFileName)
	if err := os.WriteFile(filePath, jsonBytes, 0644); err != nil {
		h.logger.CaptureError(
			fmt.Errorf("error writing metadata file: %v", err))
		return
	}

	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: []*spb.FilesItem{
					{
						Path: MetaFileName,
						Type: spb.FilesItem_WANDB,
					},
				},
			},
		},
	}

	h.handleFiles(record)
}

func (h *Handler) handleRequestAttach(record *spb.Record) {
	response := &spb.Response{
		ResponseType: &spb.Response_AttachResponse{
			AttachResponse: &spb.AttachResponse{
				Run: h.runRecord,
			},
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleRequestCancel(request *spb.CancelRequest) {
	// TODO(flow-control): implement cancel
	cancelSlot := request.GetCancelSlot()
	if cancelSlot != "" {
		h.mailbox.Cancel(cancelSlot)
	}
}

func (h *Handler) handleRequestPause() {
	h.runTimer.Pause()
	h.systemMonitor.Pause()
}

func (h *Handler) handleRequestResume() {
	h.runTimer.Resume()
	h.systemMonitor.Resume()
}

func (h *Handler) handleSystemMetrics(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleOutput(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleOutputRaw(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handlePreempting(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRun(record *spb.Record) {
	h.fwdRecordWithControl(record,
		func(control *spb.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleConfig(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleAlert(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleExit(record *spb.Record, exit *spb.RunExitRecord) {
	// stop the run timer and set the runtime
	h.runTimer.Pause()
	exit.Runtime = int32(h.runTimer.Elapsed().Seconds())

	if !h.settings.GetXSync().GetValue() {
		h.updateRunTiming()
	}

	// send the exit record
	h.fwdRecordWithControl(record,
		func(control *spb.Control) {
			control.AlwaysSend = true
			// do not write to the transaction log when syncing an offline run
			if h.settings.GetXSync().GetValue() {
				control.Local = true
			}
		},
	)
}

func (h *Handler) handleFiles(record *spb.Record) {
	if record.GetFiles() == nil {
		return
	}
	h.fwdRecord(record)
}

func (h *Handler) handleRequestGetSummary(record *spb.Record) {
	response := &spb.Response{}

	items, err := h.runSummary.ToRecords()

	// If there's an error, we still respond with the records we were
	// able to produce.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error flattening run summary: %v", err))
	}

	response.ResponseType = &spb.Response_GetSummaryResponse{
		GetSummaryResponse: &spb.GetSummaryResponse{
			Item: items,
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleRequestGetSystemMetrics(record *spb.Record) {
	sm := h.systemMonitor.GetBuffer()

	response := &spb.Response{}

	response.ResponseType = &spb.Response_GetSystemMetricsResponse{
		GetSystemMetricsResponse: &spb.GetSystemMetricsResponse{
			SystemMetrics: make(map[string]*spb.SystemMetricsBuffer),
		},
	}

	for key, samples := range sm {
		buffer := make([]*spb.SystemMetricSample, 0, len(samples.GetElements()))

		// convert samples to buffer:
		for _, sample := range samples.GetElements() {
			buffer = append(buffer, &spb.SystemMetricSample{
				Timestamp: sample.Timestamp,
				Value:     float32(sample.Value),
			})
		}
		// add to response as map key: buffer
		response.GetGetSystemMetricsResponse().SystemMetrics[key] = &spb.SystemMetricsBuffer{
			Record: buffer,
		}
	}

	h.respond(record, response)
}

func (h *Handler) handleRequestInternalMessages(record *spb.Record) {
	messages := h.terminalPrinter.Read()
	response := &spb.Response{
		ResponseType: &spb.Response_InternalMessagesResponse{
			InternalMessagesResponse: &spb.InternalMessagesResponse{
				Messages: &spb.InternalMessages{
					Warning: messages,
				},
			},
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleRequestSync(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestSenderRead(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleTelemetry(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleUseArtifact(record *spb.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestJobInput(record *spb.Record) {
	h.fwdRecord(record)
}

// handleSummary processes an update to the run summary.
//
// These records come from one of three sources:
//   - Explicit updates made by using `run.summary[...] = ...`
//   - Records from the transaction log when syncing
//   - `updateRunTiming`
func (h *Handler) handleSummary(
	record *spb.Record,
	summary *spb.SummaryRecord,
) {
	for _, update := range summary.Update {
		err := h.runSummary.SetFromRecord(update)
		if err != nil {
			h.logger.CaptureError(
				fmt.Errorf("handler: error processing summary: %v", err))
		}
	}

	for _, remove := range summary.Remove {
		h.runSummary.RemoveFromRecord(remove)
	}

	h.fwdRecord(record)
}

// updateRunTiming updates the `_wandb.runtime` summary metric which
// tracks the total duration of the run.
//
// This emits a summary record that is written to the transaction log.
func (h *Handler) updateRunTiming() {
	runtime := int(h.runTimer.Elapsed().Seconds())
	record := &spb.Record{
		RecordType: &spb.Record_Summary{
			Summary: &spb.SummaryRecord{
				Update: []*spb.SummaryItem{{
					NestedKey: []string{"_wandb", "runtime"},
					ValueJson: strconv.Itoa(runtime),
				}},
			},
		},
	}

	h.handleSummary(record, record.GetSummary())
}

func (h *Handler) handleTBrecord(record *spb.TBRecord) {
	if err := h.tbHandler.Handle(record); err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: failed to handle TB record: %v", err))
	}
}

// handleHistoryDirectly forwards history records without modification.
func (h *Handler) handleHistoryDirectly(history *spb.HistoryRecord) {
	if len(history.GetItem()) == 0 {
		return
	}

	record := &spb.Record{
		RecordType: &spb.Record_History{
			History: history,
		},
	}
	h.fwdRecord(record)
}

func (h *Handler) handleRequestNetworkStatus(record *spb.Record) {
	h.fwdRecord(record)
}

// handleRequestPartialHistory updates the run history, flushing data for
// completed steps.
func (h *Handler) handleRequestPartialHistory(
	_ *spb.Record,
	request *spb.PartialHistoryRequest,
) {
	if h.settings.GetXShared().GetValue() {
		h.handlePartialHistoryAsync(request)
	} else {
		h.handlePartialHistorySync(request)
	}
}

// handlePartialHistoryAsync updates the run history in shared mode.
//
// In "shared" mode, multiple processes (possibly running on different
// machines) write to the same run and the backend infers step numbers.
func (h *Handler) handlePartialHistoryAsync(request *spb.PartialHistoryRequest) {
	if h.partialHistory == nil {
		// NOTE: We ignore the step in shared mode.
		h.partialHistory = runhistory.New()
	}

	// Append the history items from the request to the current history record.
	//
	// We do this on a best-effort basis: errors are logged and problematic
	// metrics are ignored.
	for _, item := range request.GetItem() {
		err := h.partialHistory.SetFromRecord(item)

		if err != nil {
			h.logger.CaptureError(
				fmt.Errorf("handler: failed to set history metric: %v", err),
				"item", item)
		}
	}

	if request.GetAction() == nil || request.Action.GetFlush() {
		h.flushPartialHistory(false, 0)
	}
}

// handlePartialHistorySync updates the run history in non-shared mode.
//
// In this mode, we are the only process writing to this run.
// The main difference from shared mode is that we're responsible
// for setting step numbers.
func (h *Handler) handlePartialHistorySync(request *spb.PartialHistoryRequest) {
	if h.partialHistory == nil {
		h.partialHistory = runhistory.New()
		h.partialHistoryStep = h.runRecord.GetStartingStep()
	}

	if request.GetStep() != nil {
		step := request.Step.GetNum()
		current := h.partialHistoryStep
		if step > current {
			h.flushPartialHistory(true, step)
		} else if step < current {
			h.logger.Warn(
				"handler: ignoring partial history record",
				"step", step,
				"current", current,
			)

			h.terminalPrinter.Writef(
				"Tried to log to step %d that is less than the current step %d."+
					" Steps must be monotonically increasing, so this data"+
					" will be ignored. See https://wandb.me/define-metric"+
					" to log data out of order.",
				step,
				current,
			)
			return
		}
	}

	for _, item := range request.GetItem() {
		err := h.partialHistory.SetFromRecord(item)
		if err != nil {
			h.logger.CaptureError(
				fmt.Errorf("handler: failed to set history metric: %v", err),
				"item", item)
		}
	}

	var shouldFlush bool
	if request.GetAction() != nil {
		shouldFlush = request.GetAction().GetFlush()
	} else {
		// Default to flushing if the step is not provided.
		shouldFlush = request.GetStep() == nil
	}
	if !shouldFlush {
		return
	}

	h.flushPartialHistory(true, h.partialHistoryStep+1)
}

// flushPartialHistory finalizes and resets the accumulated run history.
//
// If useStep is true, then the emitted history record has an explicit
// step, and partialHistoryStep is updated to nextStep. Otherwise,
// nextStep is ignored.
func (h *Handler) flushPartialHistory(useStep bool, nextStep int64) {
	// Don't log anything if there are no metrics.
	if h.partialHistory == nil || h.partialHistory.IsEmpty() {
		if useStep {
			h.partialHistoryStep = nextStep
		}

		return
	}

	h.partialHistory.SetFloat(
		pathtree.PathOf("_runtime"),
		h.runTimer.Elapsed().Seconds(),
	)

	// When running in "shared" mode, there can be multiple writers to the same
	// run (for example running on different machines). In that case, the
	// backend determines the step, and the client ID identifies which metrics
	// came from the same writer. Otherwise, we must set the step explicitly.
	if h.settings.GetXShared().GetValue() {
		// TODO: useStep must be false here
		h.partialHistory.SetString(
			pathtree.PathOf("_client_id"),
			h.clientID,
		)
	} else if useStep {
		h.partialHistory.SetInt(
			pathtree.PathOf("_step"),
			h.partialHistoryStep,
		)
	}

	newMetricDefs := h.metricHandler.UpdateMetrics(h.partialHistory)
	for _, newMetric := range newMetricDefs {
		// We don't mark the record 'Local' because partial history updates
		// are not already written to the transaction log.
		h.handleMetric(&spb.Record{
			RecordType: &spb.Record_Metric{Metric: newMetric},
		})
	}
	h.metricHandler.InsertStepMetrics(h.partialHistory)

	h.runHistorySampler.SampleNext(h.partialHistory)

	if !h.skipSummary {
		h.updateRunTiming()
		h.updateSummary()
	}

	items, err := h.partialHistory.ToRecords()
	currentStep := h.partialHistoryStep

	h.partialHistory = runhistory.New()
	if useStep {
		h.partialHistoryStep = nextStep
	}

	// Report errors, but continue anyway to drop as little data as possible.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error flattening run history: %v", err))
		h.terminalPrinter.Writef(
			"There was an issue processing run metrics in step %d;"+
				" some data may be missing.",
			currentStep,
		)
	}

	historyRecord := &spb.HistoryRecord{Item: items}
	if useStep {
		historyRecord.Step = &spb.HistoryStep{Num: currentStep}
	}
	h.handleHistoryDirectly(historyRecord)
}

// updateSummary updates the summary based on the current history step.
//
// This emits a summary record that is written to the transaction log.
func (h *Handler) updateSummary() {
	updates, err := h.runSummary.UpdateSummaries(h.partialHistory)

	// We continue despite errors to update as much of the summary as we can.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error updating summary: %v", err))
	}

	if len(updates) == 0 {
		return
	}

	// We must forward these changes to the Sender which uses them to build
	// its own summary.
	h.fwdRecord(&spb.Record{
		RecordType: &spb.Record_Summary{
			Summary: &spb.SummaryRecord{
				Update: updates,
			},
		},
	})
}

// samples history items and updates the history record with the sampled values
//
// This function samples history items and updates the history record with the
// sampled values. It is used to display a subset of the history items in the
// terminal. The sampling is done using a reservoir sampling algorithm.
func (h *Handler) handleRequestSampledHistory(record *spb.Record) {
	h.respond(record, &spb.Response{
		ResponseType: &spb.Response_SampledHistoryResponse{
			SampledHistoryResponse: &spb.SampledHistoryResponse{
				Item: h.runHistorySampler.Get(),
			},
		},
	})
}

func (h *Handler) GetRun() *spb.RunRecord {
	return h.runRecord
}
