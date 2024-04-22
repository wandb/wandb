package server

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/segmentio/encoding/json"
	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/utils"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/sampler"
	"github.com/wandb/wandb/core/internal/timer"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	MetaFileName              = "wandb-metadata.json"
	SummaryFileName           = "wandb-summary.json"
	OutputFileName            = "output.log"
	DiffFileName              = "diff.patch"
	RequirementsFileName      = "requirements.txt"
	ConfigFileName            = "config.yaml"
	summaryDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	summaryDebouncerBurstSize = 1        // todo: audit burst size
)

type HandlerParams struct {
	Settings          *service.Settings
	ForwardChan       chan *service.Record
	OutChan           chan *service.Result
	Logger            *observability.CoreLogger
	Mailbox           *mailbox.Mailbox
	SummaryHandler    *SummaryHandler
	MetricHandler     *MetricHandler
	FileTransferStats filetransfer.FileTransferStats
	RunfilesUploader  runfiles.Uploader
	TBHandler         *TBHandler
	SystemMonitor     *monitor.SystemMonitor
}

// Handler is the handler for a stream it handles the incoming messages, processes them
// and passes them to the writer
type Handler struct {
	// ctx is the context for the handler
	ctx context.Context

	// settings is the settings for the handler
	settings *service.Settings

	// logger is the logger for the handler
	logger *observability.CoreLogger

	// fwdChan is the channel for forwarding messages to the next component
	fwdChan chan *service.Record

	// outChan is the channel for sending results to the client
	outChan chan *service.Result

	// runRecord is the runRecord record received from the server
	runRecord *service.RunRecord

	// samplers is the map of samplers for all the history metrics that are
	// being tracked, the result of the samplers will be used to display the
	// the sparkline in the terminal
	//
	// TODO: currently only values that can be cast to float32 are supported
	samplers map[string]*sampler.ReservoirSampler[float32]

	runMetric *runmetric.RunMetricHanlder

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor

	// tbHandler is the tensorboard handler
	tbHandler *TBHandler

	// runTimer is used to track the run start and execution times
	runTimer *timer.Timer

	// runfilesUploaderOrNil manages uploading a run's files
	//
	// It may be nil when offline.
	runfilesUploaderOrNil runfiles.Uploader

	// fileTransferStats reports file upload/download statistics
	fileTransferStats filetransfer.FileTransferStats

	// runDelta is the current partial run summary that
	// was updated since the last time we sent summary
	runDeltaSummary *runsummary.RunSummary

	// runFullSummary is the full run summary that contains
	// all the keys
	runFullSummary *runsummary.RunSummary

	// summaryDebouncer is the debouncer for summary updates
	summaryDebouncer *debounce.Debouncer

	// runHistory is the current active history entry being updated
	runHistory *runhistory.RunHistory

	// internalPrinter is the internal messages handler for the stream
	internalPrinter *observability.Printer[string]

	mailbox *mailbox.Mailbox
}

// NewHandler creates a new handler
func NewHandler(
	ctx context.Context,
	params *HandlerParams,
) *Handler {
	return &Handler{
		ctx:             ctx,
		logger:          params.Logger,
		internalPrinter: observability.NewPrinter[string](),
		runDeltaSummary: runsummary.New(),
		runFullSummary:  runsummary.New(),
		summaryDebouncer: debounce.NewDebouncer(
			summaryDebouncerRateLimit,
			summaryDebouncerBurstSize,
			params.Logger,
		),
		runMetric:             runmetric.NewMetricHandler(),
		runTimer:              timer.New(),
		fwdChan:               params.ForwardChan,
		outChan:               params.OutChan,
		settings:              params.Settings,
		systemMonitor:         params.SystemMonitor,
		tbHandler:             params.TBHandler,
		runfilesUploaderOrNil: params.RunfilesUploader,
		fileTransferStats:     params.FileTransferStats,
		mailbox:               params.Mailbox,
	}
}

// Do starts the handler
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
	h.logger.Debug("handler: Close: closed", "stream_id", h.settings.RunId)
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

	control := record.GetControl()
	for _, opt := range controlOptions {
		opt(control)
	}
	h.fwdRecord(record)
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *service.Record) {
	h.summaryDebouncer.Debounce(h.debounceSummary)
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
		h.handleHistory(x.History)
	case *service.Record_LinkArtifact:
		h.handleLinkArtifact(record)
	case *service.Record_Metric:
		h.handleMetric(record, x.Metric)
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
		h.handleTBrecord(record)
	case *service.Record_Telemetry:
		h.handleTelemetry(record)
	case *service.Record_UseArtifact:
		h.handleUseArtifact(record)
	case nil:
		err := fmt.Errorf("handler: handleRecord: record type is nil")
		h.logger.CaptureFatalAndPanic("error handling record", err)
	default:
		err := fmt.Errorf("handler: handleRecord: unknown record type %T", x)
		h.logger.CaptureFatalAndPanic("error handling record", err)
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
		// not implemented in the old handler
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
		err := fmt.Errorf("handler: handleRequest: request type is nil")
		h.logger.CaptureFatalAndPanic("error handling request", err)
	default:
		err := fmt.Errorf("handler: handleRequest: unknown request type %T", x)
		h.logger.CaptureFatalAndPanic("error handling request", err)
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

// handleMetric handles a metric record and adds it to the run metric
// if the metric has a step field, it will also add a step metric
// and send it to the sender
func (h *Handler) handleMetric(record *service.Record, metric *service.MetricRecord) {

	if stepMetric := h.runMetric.AddStepMetric(metric); stepMetric != nil {
		stepRecord := &service.Record{
			RecordType: &service.Record_Metric{
				Metric: stepMetric,
			},
		}
		h.fwdRecordWithControl(stepRecord,
			func(control *service.Control) {
				control.Local = true
			},
		)
	}

	err := h.runMetric.AddMetric(metric)
	if err != nil {
		h.logger.CaptureError("error adding metric", err)
		return
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
		h.systemMonitor.Stop()
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		h.handleRequestPartialHistory(
			nil,
			&service.PartialHistoryRequest{},
		)
	case service.DeferRequest_FLUSH_TB:
		h.tbHandler.Close()
	case service.DeferRequest_FLUSH_SUM:
		h.handleSummary(nil, &service.SummaryRecord{})
		h.summaryDebouncer.Flush(h.debounceSummary)
		h.uploadSummaryFile()
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
		err := fmt.Errorf("handleDefer: unknown defer state %v", request.State)
		h.logger.CaptureError("unknown defer state", err)
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

func (h *Handler) handleLinkArtifact(record *service.Record) {
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
	versionString := fmt.Sprintf("%s+%s", version.Version, h.ctx.Value(observability.Commit("commit")))
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

	// start the run timer
	startTime := run.StartTime.AsTime()
	h.runTimer.Start(&startTime)

	if h.runRecord, ok = proto.Clone(run).(*service.RunRecord); !ok {
		err := fmt.Errorf("handleRunStart: failed to clone run")
		h.logger.CaptureFatalAndPanic("error handling run start", err)
	}
	h.fwdRecord(record)

	// TODO: mark OutputFileName as a WANDB file
	_ = OutputFileName

	// start the system monitor
	if !h.settings.GetXDisableStats().GetValue() {
		h.systemMonitor.Do()
	}

	// save code and patch
	if h.settings.GetSaveCode().GetValue() {
		h.handleCodeSave()
		h.handlePatchSave()
	}

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

	if !h.settings.GetXDisableStats().GetValue() {
		systemInfo := h.systemMonitor.Probe()
		if systemInfo != nil {
			proto.Merge(metadata, systemInfo)
		}
	}
	h.handleMetadata(metadata)

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

	mo := protojson.MarshalOptions{
		Indent: "  ",
		// EmitUnpopulated: true,
	}
	jsonBytes, err := mo.Marshal(request)
	if err != nil {
		h.logger.CaptureError("error marshalling metadata", err)
		return
	}
	filePath := filepath.Join(h.settings.GetFilesDir().GetValue(), MetaFileName)
	if err := os.WriteFile(filePath, jsonBytes, 0644); err != nil {
		h.logger.CaptureError("error writing metadata file", err)
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
	h.systemMonitor.Stop()
}

func (h *Handler) handleRequestResume() {
	h.runTimer.Resume()
	h.systemMonitor.Do()
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

func (h *Handler) updateSummary(summary *service.SummaryRecord) {
	h.runDeltaSummary.ApplyChangeRecord(summary, func(err error) {
		h.logger.CaptureError("Error updating run delta summary", err)
	})
	h.runFullSummary.ApplyChangeRecord(summary, func(err error) {
		h.logger.CaptureError("Error updating run full summary", err)
	})
	h.summaryDebouncer.SetNeedsDebounce()
}

func (h *Handler) handleExit(record *service.Record, exit *service.RunExitRecord) {
	// stop the run timer and set the runtime
	h.runTimer.Pause()
	exit.Runtime = int32(h.runTimer.Elapsed().Seconds())

	// update summary with runtime
	h.handleSummary(nil, &service.SummaryRecord{})

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

	// TODO: fix this
	items := h.runFullSummary.FlattenTree()
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
	messages := h.internalPrinter.Read()
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

func (h *Handler) uploadSummaryFile() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	serializedSummary, err := h.runFullSummary.Serialize(pathtree.FormatJson)

	if err != nil {
		err = fmt.Errorf("failed to marshal summary: %w", err)
		h.logger.Error("handler: uploadSummaryFile:", "error", err)
		return
	}

	file := filepath.Join(h.settings.GetFilesDir().GetValue(), SummaryFileName)

	if err := os.WriteFile(file, serializedSummary, 0644); err != nil {
		err = fmt.Errorf("failed to write summary file: %w", err)
		h.logger.Error("handler: uploadSummaryFile:", "error", err)
		return
	}

	if h.runfilesUploaderOrNil != nil {
		// TODO: mark as WANDB file
		h.runfilesUploaderOrNil.UploadNow(SummaryFileName)
	}
}

func (h *Handler) debounceSummary() {

	update := h.runDeltaSummary.FlattenTree()

	record := &service.Record{
		RecordType: &service.Record_Summary{
			Summary: &service.SummaryRecord{
				Update: update,
			},
		},
	}
	h.fwdRecord(record)

	// since we have sent the delta summary, we can clear it
	h.runDeltaSummary = runsummary.New()
}

func (h *Handler) handleSummary(_ *service.Record, summary *service.SummaryRecord) {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	runtime := int32(h.runTimer.Elapsed().Seconds())
	// update summary with runtime
	summary.Update = append(summary.Update, &service.SummaryItem{
		Key:       "_wandb",
		NestedKey: []string{"runtime"},
		ValueJson: fmt.Sprintf("%d", runtime),
	})
	h.updateSummary(summary)
}

func (h *Handler) handleTBrecord(record *service.Record) {
	err := h.tbHandler.Handle(record)
	if err != nil {
		h.logger.CaptureError("error handling tbrecord", err)
	}
}

// The main entry point for history records.
//
// This processes a history record and forwards it to the writer.
func (h *Handler) handleHistory(history *service.HistoryRecord) {
	if history == nil || history.Item == nil {
		return
	}
	runtime := h.runTimer.Elapsed().Seconds()
	history.Item = append(history.Item, &service.HistoryItem{
		Key:       "_runtime",
		ValueJson: fmt.Sprintf("%f", runtime),
	})
	if !h.settings.GetXShared().GetValue() {
		history.Item = append(history.Item, &service.HistoryItem{
			Key:       "_step",
			ValueJson: fmt.Sprintf("%d", history.GetStep().GetNum()),
		})
	}

	// impute missing step metrics if needed
	imputed := []*service.HistoryItem{}
	for _, item := range history.GetItem() {
		key := item.GetKey()
		needs := h.checkNeedsImputation(key)
		if needs {
			// we use the summary value of the metric as the algorithm
			// for imputing the step metric
			// TODO: fix this (we don't want to use Tree() here)
			if val, ok := h.runFullSummary.Tree()[key]; ok {
				// TODO: add nested key support
				value, err := json.Marshal(val)
				if err != nil {
					h.logger.CaptureError("error marshalling step metric value", err)
					continue
				}
				imputed = append(imputed, &service.HistoryItem{
					Key:       item.GetKey(),
					ValueJson: string(value),
				})
			}
		}
	}
	history.Item = append(history.Item, imputed...)

	record := &service.Record{
		RecordType: &service.Record_History{
			History: history,
		},
	}
	h.fwdRecord(record)

	h.sampleHistory(history)

	// update summary with history record
	update := []*service.SummaryItem{}
	for _, item := range history.GetItem() {
		update = append(update, &service.SummaryItem{
			Key:       item.Key,
			NestedKey: item.NestedKey,
			ValueJson: item.ValueJson,
		})
	}
	summary := &service.SummaryRecord{
		Update: update,
	}
	h.updateSummary(summary)
}

func (h *Handler) handleRequestNetworkStatus(record *service.Record) {
	h.fwdRecord(record)
}

// The main entry point for partial history records.
//
// This collects partial history records until a full history record is
// received. A full history record is received when the condition for flushing
// the history record is met. The condition for flushing the history record is
// determined by the action in the partial history request and the step number.
// Once a full history record is received, it is forwarded to the writer.
func (h *Handler) handleRequestPartialHistory(_ *service.Record, request *service.PartialHistoryRequest) {
	if h.settings.GetXShared().GetValue() {
		h.handlePartialHistoryAsync(request)
	} else {
		h.handlePartialHistorySync(request)
	}
}

// The main entry point for partial history records in the shared mode.
//
// This collects partial history records until a full history record is
// received. This is the asynchronous version of handlePartialHistory.
// In this mode, the server will assign a step number to the history record.
func (h *Handler) handlePartialHistoryAsync(request *service.PartialHistoryRequest) {
	// This is the first partial history record we receive
	if h.runHistory == nil {
		h.runHistory = runhistory.New(nil)
	}
	h.runHistory.ApplyUpdate(request.GetItem(), func(err error) {
		h.logger.CaptureError("Error updating run history", err)
	})

	// Flush the history record and start to collect a new one
	if request.GetAction() == nil || request.GetAction().GetFlush() {
		items := h.runHistory.FlattenTree()
		h.handleHistory(&service.HistoryRecord{
			Item: items,
		})
	}
}

// The main entry point for partial history records in the non-shared mode.
//
// This collects partial history records until a full history record is
// received. This is the synchronous version of handlePartialHistory.
// In this mode, the client will assign a step number to the history record.
// The client is responsible for ensuring that the step number is monotonically
// increasing.
func (h *Handler) handlePartialHistorySync(request *service.PartialHistoryRequest) {

	// This is the first partial history record we receive
	// for this step, so we need to initialize the history record
	// and step. If the user provided a step in the request,
	// use that, otherwise use 0.
	if h.runHistory == nil {
		// Although technically the backend allows negative steps,
		// in practice it is all set up to work with non-negative steps
		// so if we receive a negative step, it will be discarded
		step := h.runRecord.GetStartingStep()
		h.runHistory = runhistory.New(&step)
	}

	// The HistoryRecord struct is responsible for tracking data related to
	//	a single step in the history. Users can send multiple partial history
	//	records for a single step. Each partial history record contains a
	//	step number, a flush flag, and a list of history items.
	//
	// The step number indicates the step number for the history record. The
	// flush flag determines whether the history record should be flushed
	// after processing the request. The history items are appended to the
	// existing history record.
	//
	// The following logic is used to process the request:
	//
	// -  If the request includes a step number and the step number is greater
	//		than the current step number, the current history record is flushed
	//		and a new history record is created.
	// - If the step number in the request is less than the current step number,
	//		we ignore the request and log a warning.
	// 		NOTE: the server requires the steps of the history records
	// 		to be monotonically increasing.
	// -  If the step number in the request matches the current step number, the
	//		history items are appended to the current history record.
	//
	// - If the request has a flush flag, another flush might occur after for
	// the current history record after processing the request.
	//
	// - If the request doesn't have a step, and doesn't have a flush flag, this
	// is equivalent to step being equal to the current step number and a flush
	// flag being set to true.
	if request.GetStep() != nil {
		step := request.Step.GetNum()
		current := *h.runHistory.Step
		if step > current {
			items := h.runHistory.FlattenTree()
			history := &service.HistoryRecord{
				Step: &service.HistoryStep{
					Num: *h.runHistory.Step,
				},
				Item: items,
			}
			h.handleHistory(history)
			h.runHistory = runhistory.New(&step)
		} else if step < current {
			h.logger.CaptureWarn("handlePartialHistorySync: ignoring history record", "step", step, "current", current)
			msg := fmt.Sprintf("steps must be monotonically increasing, received history record for a step (%d) "+
				"that is less than the current step (%d) this data will be ignored. if you need to log data out of order, "+
				"please see: https://wandb.me/define-metric", step, current)
			h.internalPrinter.Write(msg)
			return
		}
	}

	// Append the history items from the request to the current history record.
	h.runHistory.ApplyUpdate(request.GetItem(), func(err error) {
		h.logger.CaptureError("Error updating run history", err)
	})

	// Flush the history record and start to collect a new one with
	// the next step number.
	if (request.GetStep() == nil && request.GetAction() == nil) || request.GetAction().GetFlush() {
		items := h.runHistory.FlattenTree()
		history := &service.HistoryRecord{
			Step: &service.HistoryStep{
				Num: *h.runHistory.Step,
			},
			Item: items,
		}
		h.handleHistory(history)
		step := *h.runHistory.Step + 1
		h.runHistory = runhistory.New(&step)
	}
}

// sync history item with step metric if needed

// This function checks if a history item matches a defined metric or a glob
// metric. If the step metric is not part of the history record, and it needs to
// be synced, the function imputes the step metric and returns it.
func (h *Handler) checkNeedsImputation(key string) bool {

	// check if history item matches a defined metric or a glob metric
	metric, ok := h.runMetric.MatchMetric(key)
	if metric != nil && !ok {
		record := &service.Record{
			RecordType: &service.Record_Metric{
				Metric: metric,
			},
			Control: &service.Control{
				Local: true,
			},
		}
		h.handleMetric(record, metric)
	}

	stepKey := metric.GetStepMetric()

	// check if step metric is defined and if it needs to be synced
	if stepKey == "" || !metric.GetOptions().GetStepSync() {
		return false
	}

	// check if step metric is already in history
	// TODO: fix this (we don't want to use Tree() here)
	if _, ok := h.runHistory.Tree()[stepKey]; ok {
		return false
	}
	return true
}

// samples history items and updates the history record with the sampled values
//
// This function samples history items and updates the history record with the
// sampled values. It is used to display a subset of the history items in the
// terminal. The sampling is done using a reservoir sampling algorithm.
func (h *Handler) handleRequestSampledHistory(record *service.Record) {
	response := &service.Response{}

	if h.samplers != nil {
		var items []*service.SampledHistoryItem
		for key, sampler := range h.samplers {
			values := sampler.Sample()
			item := &service.SampledHistoryItem{
				Key:         key,
				ValuesFloat: values,
			}
			items = append(items, item)
		}

		response.ResponseType = &service.Response_SampledHistoryResponse{
			SampledHistoryResponse: &service.SampledHistoryResponse{
				Item: items,
			},
		}
	}

	h.respond(record, response)
}

// sample history items and update the samplers map before flushing the history
// record as these values are finalized for the current step
func (h *Handler) sampleHistory(history *service.HistoryRecord) {
	// initialize the samplers map if it doesn't exist
	if h.samplers == nil {
		h.samplers = make(map[string]*sampler.ReservoirSampler[float32])
	}

	for _, item := range history.GetItem() {
		var value float32
		if err := json.Unmarshal([]byte(item.ValueJson), &value); err != nil {
			// ignore items that cannot be parsed as float32
			continue
		}

		// create a new sampler if it doesn't exist
		if _, ok := h.samplers[item.Key]; !ok {
			h.samplers[item.Key] = sampler.NewReservoirSampler[float32](48, 0.0005)
		}

		// add the new value to the sampler
		h.samplers[item.Key].Add(value)
	}
}

func (h *Handler) GetRun() *service.RunRecord {
	return h.runRecord
}
