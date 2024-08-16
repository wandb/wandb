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
	"github.com/wandb/wandb/core/pkg/service"
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
	Settings          *service.Settings
	FwdChan           chan *service.Record
	OutChan           chan *service.Result
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
	settings *service.Settings

	// clientID is an ID for this process.
	//
	// This identifies the process that uploaded a set of metrics when
	// running in "shared" mode, where there may be multiple writers for
	// the same run.
	clientID string

	// logger is the logger for the handler
	logger *observability.CoreLogger

	// fwdChan is the channel for forwarding messages to the next component
	fwdChan chan *service.Record

	// outChan is the channel for sending results to the client
	outChan chan *service.Result

	// runTimer is used to track the run start and execution times
	runTimer *timer.Timer

	// runRecord is the runRecord record received from the server
	runRecord *service.RunRecord

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
	metadata *service.MetadataRequest

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
func (h *Handler) Do(inChan <-chan *service.Record) {
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
func (h *Handler) respond(record *service.Record, response *service.Response) {
	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.outChan <- result
}

// fwdRecord forwards a record to the next component
func (h *Handler) fwdRecord(record *service.Record) {
	if record == nil {
		return
	}
	h.fwdChan <- record
}

// fwdRecordWithControl forwards a record to the next component with control options
func (h *Handler) fwdRecordWithControl(record *service.Record, controlOptions ...func(*service.Control)) {
	if record == nil {
		return
	}

	if record.GetControl() == nil {
		record.Control = &service.Control{}
	}

	for _, opt := range controlOptions {
		opt(record.Control)
	}
	h.fwdRecord(record)
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *service.Record) {
	switch x := record.RecordType.(type) {
	case *service.Record_Alert:
		h.handleAlert(record)
	case *service.Record_Artifact:
		h.handleArtifact(record)
	case *service.Record_Config:
		h.handleConfig(record)
	case *service.Record_Exit:
		h.handleExit(record, x.Exit)
	case *service.Record_Files:
		h.handleFiles(record)
	case *service.Record_Final:
		h.handleFinal()
	case *service.Record_Footer:
		h.handleFooter()
	case *service.Record_Header:
		h.handleHeader(record)
	case *service.Record_History:
		h.handleHistoryDirectly(x.History)
	case *service.Record_NoopLinkArtifact:
		// Removed but kept to avoid panics
	case *service.Record_Metric:
		h.handleMetric(record)
	case *service.Record_Output:
		h.handleOutput(record)
	case *service.Record_OutputRaw:
		h.handleOutputRaw(record)
	case *service.Record_Preempting:
		h.handlePreempting(record)
	case *service.Record_Request:
		h.handleRequest(record)
	case *service.Record_Run:
		h.handleRun(record)
	case *service.Record_Stats:
		h.handleSystemMetrics(record)
	case *service.Record_Summary:
		h.handleSummary(record, x.Summary)
	case *service.Record_Tbrecord:
		h.handleTBrecord(x.Tbrecord)
	case *service.Record_Telemetry:
		h.handleTelemetry(record)
	case *service.Record_UseArtifact:
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
func (h *Handler) handleRequest(record *service.Record) {
	request := record.GetRequest()
	switch x := request.RequestType.(type) {
	case *service.Request_Login:
		h.handleRequestLogin(record)
	case *service.Request_CheckVersion:
		h.handleRequestCheckVersion(record)
	case *service.Request_RunStatus:
		h.handleRequestRunStatus(record)
	case *service.Request_Metadata:
		h.handleMetadata(x.Metadata)
	case *service.Request_SummaryRecord:
		// TODO: handles sending summary file
	case *service.Request_TelemetryRecord:
		// TODO: handles sending telemetry record
	case *service.Request_TestInject:
		// not implemented in the old handler
	case *service.Request_JobInfo:
		// not implemented in the old handler
	case *service.Request_Status:
		h.handleRequestStatus(record)
	case *service.Request_SenderMark:
		h.handleRequestSenderMark(record)
	case *service.Request_StatusReport:
		h.handleRequestStatusReport(record)
	case *service.Request_Keepalive:
		// keepalive is a no-op
	case *service.Request_Shutdown:
		h.handleRequestShutdown(record)
	case *service.Request_Defer:
		h.handleRequestDefer(record, x.Defer)
	case *service.Request_GetSummary:
		h.handleRequestGetSummary(record)
	case *service.Request_NetworkStatus:
		h.handleRequestNetworkStatus(record)
	case *service.Request_PartialHistory:
		h.handleRequestPartialHistory(record, x.PartialHistory)
	case *service.Request_PollExit:
		h.handleRequestPollExit(record)
	case *service.Request_RunStart:
		h.handleRequestRunStart(record, x.RunStart)
	case *service.Request_SampledHistory:
		h.handleRequestSampledHistory(record)
	case *service.Request_ServerInfo:
		h.handleRequestServerInfo(record)
	case *service.Request_PythonPackages:
		h.handleRequestPythonPackages(record, x.PythonPackages)
	case *service.Request_StopStatus:
		h.handleRequestStopStatus(record)
	case *service.Request_LogArtifact:
		h.handleRequestLogArtifact(record)
	case *service.Request_LinkArtifact:
		h.handleRequestLinkArtifact(record)
	case *service.Request_DownloadArtifact:
		h.handleRequestDownloadArtifact(record)
	case *service.Request_Attach:
		h.handleRequestAttach(record)
	case *service.Request_Pause:
		h.handleRequestPause()
	case *service.Request_Resume:
		h.handleRequestResume()
	case *service.Request_Cancel:
		h.handleRequestCancel(x.Cancel)
	case *service.Request_GetSystemMetrics:
		h.handleRequestGetSystemMetrics(record)
	case *service.Request_InternalMessages:
		h.handleRequestInternalMessages(record)
	case *service.Request_Sync:
		h.handleRequestSync(record)
	case *service.Request_SenderRead:
		h.handleRequestSenderRead(record)
	case *service.Request_JobInput:
		h.handleRequestJobInput(record)
	case nil:
		h.logger.CaptureFatalAndPanic(
			errors.New("handler: handleRequest: request type is nil"))
	default:
		h.logger.CaptureFatalAndPanic(
			fmt.Errorf("handler: handleRequest: unknown request type %T", x))
	}
}

func (h *Handler) handleRequestLogin(record *service.Record) {
	// TODO: implement login if it is needed
	if record.GetControl().GetReqResp() {
		h.respond(record, &service.Response{})
	}
}

func (h *Handler) handleRequestCheckVersion(record *service.Record) {
	// TODO: implement check version
	h.respond(record, &service.Response{})
}

func (h *Handler) handleRequestRunStatus(record *service.Record) {
	// TODO(flow-control): implement run status
	h.respond(record, &service.Response{})
}

func (h *Handler) handleRequestStatus(record *service.Record) {
	h.respond(record, &service.Response{})
}

func (h *Handler) handleRequestSenderMark(_ *service.Record) {
	// TODO(flow-control): implement sender mark
}

func (h *Handler) handleRequestStatusReport(_ *service.Record) {
	// TODO(flow-control): implement status report
}

func (h *Handler) handleRequestShutdown(record *service.Record) {
	h.respond(record, &service.Response{})
}

func (h *Handler) handleMetric(record *service.Record) {
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

func (h *Handler) handleRequestDefer(record *service.Record, request *service.DeferRequest) {
	switch request.State {
	case service.DeferRequest_BEGIN:
	case service.DeferRequest_FLUSH_RUN:
	case service.DeferRequest_FLUSH_STATS:
		// stop the system monitor to ensure that we don't send any more system metrics
		// after the run has exited
		h.systemMonitor.Finish()
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		// This will force the content of h.runHistory to be flushed and sent
		// over to the sender.
		//
		// Since the data of the PartialHistoryRequest is empty it will not
		// change the content of h.runHistory, but it will trigger flushing
		// of h.runHistory content, because the flush action is set to true.
		// Hence, we are guranteed that the content of h.runHistory is sent
		h.handleRequestPartialHistory(
			nil,
			&service.PartialHistoryRequest{
				Action: &service.HistoryAction{
					Flush: true,
				},
			},
		)
	case service.DeferRequest_FLUSH_TB:
	case service.DeferRequest_FLUSH_SUM:
	case service.DeferRequest_FLUSH_DEBOUNCER:
	case service.DeferRequest_FLUSH_OUTPUT:
	case service.DeferRequest_FLUSH_JOB:
	case service.DeferRequest_FLUSH_DIR:
	case service.DeferRequest_FLUSH_FP:
		if h.runfilesUploaderOrNil != nil {
			h.runfilesUploaderOrNil.UploadRemaining()
		}
	case service.DeferRequest_JOIN_FP:
	case service.DeferRequest_FLUSH_FS:
	case service.DeferRequest_FLUSH_FINAL:
		h.handleFinal()
		h.handleFooter()
	case service.DeferRequest_END:
		h.fileTransferStats.SetDone()
	default:
		h.logger.CaptureError(
			fmt.Errorf("handleDefer: unknown defer state %v", request.State))
	}
	// Need to clone the record to avoid race condition with the writer
	record = proto.Clone(record).(*service.Record)
	h.fwdRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
		func(control *service.Control) {
			control.Local = true
		},
	)
}

func (h *Handler) handleRequestStopStatus(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleArtifact(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestLogArtifact(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestDownloadArtifact(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestLinkArtifact(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestPollExit(record *service.Record) {
	var pollExitResponse *service.PollExitResponse
	if h.fileTransferStats != nil {
		pollExitResponse = &service.PollExitResponse{
			PusherStats: h.fileTransferStats.GetFilesStats(),
			FileCounts:  h.fileTransferStats.GetFileCounts(),
			Done:        h.fileTransferStats.IsDone(),
		}
	} else {
		pollExitResponse = &service.PollExitResponse{
			Done: true,
		}
	}

	response := &service.Response{
		ResponseType: &service.Response_PollExitResponse{
			PollExitResponse: pollExitResponse,
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleHeader(record *service.Record) {
	// populate with version info
	versionString := fmt.Sprintf("%s+%s", version.Version, h.commit)
	record.GetHeader().VersionInfo = &service.VersionInfo{
		Producer:    versionString,
		MinConsumer: version.MinServerVersion,
	}
	h.fwdRecordWithControl(
		record,
		func(control *service.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleFinal() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}
	record := &service.Record{
		RecordType: &service.Record_Final{
			Final: &service.FinalRecord{},
		},
	}
	h.fwdRecordWithControl(
		record,
		func(control *service.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleFooter() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}
	record := &service.Record{
		RecordType: &service.Record_Footer{
			Footer: &service.FooterRecord{},
		},
	}
	h.fwdRecordWithControl(
		record,
		func(control *service.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleRequestServerInfo(record *service.Record) {
	h.fwdRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleRequestRunStart(record *service.Record, request *service.RunStartRequest) {
	var ok bool
	run := request.Run

	// offsset by run.Runtime to account for potential run branching
	startTime := run.StartTime.AsTime().Add(time.Duration(-run.Runtime) * time.Second)
	// start the run timer
	h.runTimer.Start(&startTime)

	if h.runRecord, ok = proto.Clone(run).(*service.RunRecord); !ok {
		h.logger.CaptureFatalAndPanic(
			errors.New("handleRunStart: failed to clone run"))
	}
	h.fwdRecord(record)
	// NOTE: once this request arrives in the sender,
	// the latter will start its filestream and uploader

	// initialize the run metadata from settings
	var git *service.GitRepoRecord
	if run.GetGit().GetRemoteUrl() != "" || run.GetGit().GetCommit() != "" {
		git = &service.GitRepoRecord{
			RemoteUrl: run.GetGit().GetRemoteUrl(),
			Commit:    run.GetGit().GetCommit(),
		}
	}

	metadata := &service.MetadataRequest{
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

	h.respond(record, &service.Response{})
}

func (h *Handler) handleRequestPythonPackages(_ *service.Record, request *service.PythonPackagesRequest) {
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
	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: RequirementsFileName,
						Type: service.FilesItem_WANDB,
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
	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: filepath.Join("code", programRelative),
						Type: service.FilesItem_WANDB,
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

	var files []*service.FilesItem

	filesDirPath := h.settings.GetFilesDir().GetValue()
	file := filepath.Join(filesDirPath, DiffFileName)
	if err := git.SavePatch("HEAD", file); err != nil {
		h.logger.Error("error generating diff", "error", err)
	} else {
		files = append(files, &service.FilesItem{Path: DiffFileName, Type: service.FilesItem_WANDB})
	}

	if output, err := git.LatestCommit("@{u}"); err != nil {
		h.logger.Error("error getting latest commit", "error", err)
	} else {
		diffFileName := fmt.Sprintf("diff_%s.patch", output)
		file = filepath.Join(filesDirPath, diffFileName)
		if err := git.SavePatch("@{u}", file); err != nil {
			h.logger.Error("error generating diff", "error", err)
		} else {
			files = append(files, &service.FilesItem{Path: diffFileName, Type: service.FilesItem_WANDB})
		}
	}

	if len(files) == 0 {
		return
	}

	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: files,
			},
		},
	}
	h.handleFiles(record)
}

func (h *Handler) handleMetadata(request *service.MetadataRequest) {
	// TODO: Sending metadata as a request for now, eventually this should be turned into
	//  a record and stored in the transaction log
	if h.settings.GetXDisableMeta().GetValue() {
		return
	}

	if h.metadata == nil {
		h.metadata = proto.Clone(request).(*service.MetadataRequest)
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

	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: MetaFileName,
						Type: service.FilesItem_WANDB,
					},
				},
			},
		},
	}

	h.handleFiles(record)
}

func (h *Handler) handleRequestAttach(record *service.Record) {
	response := &service.Response{
		ResponseType: &service.Response_AttachResponse{
			AttachResponse: &service.AttachResponse{
				Run: h.runRecord,
			},
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleRequestCancel(request *service.CancelRequest) {
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

func (h *Handler) handleSystemMetrics(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleOutput(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleOutputRaw(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handlePreempting(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRun(record *service.Record) {
	h.fwdRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleConfig(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleAlert(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleExit(record *service.Record, exit *service.RunExitRecord) {
	// stop the run timer and set the runtime
	h.runTimer.Pause()
	exit.Runtime = int32(h.runTimer.Elapsed().Seconds())

	if !h.settings.GetXSync().GetValue() {
		h.updateRunTiming()
	}

	// send the exit record
	h.fwdRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
			// do not write to the transaction log when syncing an offline run
			if h.settings.GetXSync().GetValue() {
				control.Local = true
			}
		},
	)
}

func (h *Handler) handleFiles(record *service.Record) {
	if record.GetFiles() == nil {
		return
	}
	h.fwdRecord(record)
}

func (h *Handler) handleRequestGetSummary(record *service.Record) {
	response := &service.Response{}

	items, err := h.runSummary.ToRecords()

	// If there's an error, we still respond with the records we were
	// able to produce.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error flattening run summary: %v", err))
	}

	response.ResponseType = &service.Response_GetSummaryResponse{
		GetSummaryResponse: &service.GetSummaryResponse{
			Item: items,
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleRequestGetSystemMetrics(record *service.Record) {
	sm := h.systemMonitor.GetBuffer()

	response := &service.Response{}

	response.ResponseType = &service.Response_GetSystemMetricsResponse{
		GetSystemMetricsResponse: &service.GetSystemMetricsResponse{
			SystemMetrics: make(map[string]*service.SystemMetricsBuffer),
		},
	}

	for key, samples := range sm {
		buffer := make([]*service.SystemMetricSample, 0, len(samples.GetElements()))

		// convert samples to buffer:
		for _, sample := range samples.GetElements() {
			buffer = append(buffer, &service.SystemMetricSample{
				Timestamp: sample.Timestamp,
				Value:     float32(sample.Value),
			})
		}
		// add to response as map key: buffer
		response.GetGetSystemMetricsResponse().SystemMetrics[key] = &service.SystemMetricsBuffer{
			Record: buffer,
		}
	}

	h.respond(record, response)
}

func (h *Handler) handleRequestInternalMessages(record *service.Record) {
	messages := h.terminalPrinter.Read()
	response := &service.Response{
		ResponseType: &service.Response_InternalMessagesResponse{
			InternalMessagesResponse: &service.InternalMessagesResponse{
				Messages: &service.InternalMessages{
					Warning: messages,
				},
			},
		},
	}
	h.respond(record, response)
}

func (h *Handler) handleRequestSync(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestSenderRead(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleTelemetry(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleUseArtifact(record *service.Record) {
	h.fwdRecord(record)
}

func (h *Handler) handleRequestJobInput(record *service.Record) {
	h.fwdRecord(record)
}

// handleSummary processes an update to the run summary.
//
// These records come from one of three sources:
//   - Explicit updates made by using `run.summary[...] = ...`
//   - Records from the transaction log when syncing
//   - `updateRunTiming`
func (h *Handler) handleSummary(
	record *service.Record,
	summary *service.SummaryRecord,
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
	record := &service.Record{
		RecordType: &service.Record_Summary{
			Summary: &service.SummaryRecord{
				Update: []*service.SummaryItem{{
					NestedKey: []string{"_wandb", "runtime"},
					ValueJson: strconv.Itoa(runtime),
				}},
			},
		},
	}

	h.handleSummary(record, record.GetSummary())
}

func (h *Handler) handleTBrecord(record *service.TBRecord) {
	if err := h.tbHandler.Handle(record); err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: failed to handle TB record: %v", err))
	}
}

// handleHistoryDirectly forwards history records without modification.
func (h *Handler) handleHistoryDirectly(history *service.HistoryRecord) {
	if len(history.GetItem()) == 0 {
		return
	}

	record := &service.Record{
		RecordType: &service.Record_History{
			History: history,
		},
	}
	h.fwdRecord(record)
}

func (h *Handler) handleRequestNetworkStatus(record *service.Record) {
	h.fwdRecord(record)
}

// handleRequestPartialHistory updates the run history, flushing data for
// completed steps.
func (h *Handler) handleRequestPartialHistory(
	_ *service.Record,
	request *service.PartialHistoryRequest,
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
func (h *Handler) handlePartialHistoryAsync(request *service.PartialHistoryRequest) {
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
func (h *Handler) handlePartialHistorySync(request *service.PartialHistoryRequest) {
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
		h.handleMetric(&service.Record{
			RecordType: &service.Record_Metric{Metric: newMetric},
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

	historyRecord := &service.HistoryRecord{Item: items}
	if useStep {
		historyRecord.Step = &service.HistoryStep{Num: currentStep}
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
	h.fwdRecord(&service.Record{
		RecordType: &service.Record_Summary{
			Summary: &service.SummaryRecord{
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
func (h *Handler) handleRequestSampledHistory(record *service.Record) {
	h.respond(record, &service.Response{
		ResponseType: &service.Response_SampledHistoryResponse{
			SampledHistoryResponse: &service.SampledHistoryResponse{
				Item: h.runHistorySampler.Get(),
			},
		},
	})
}

func (h *Handler) GetRun() *service.RunRecord {
	return h.runRecord
}
