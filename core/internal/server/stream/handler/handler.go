package handler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/lib/corelib"
	"github.com/wandb/wandb/core/internal/lib/fileslib"
	"github.com/wandb/wandb/core/internal/lib/gitlib"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/server/consts"
	"github.com/wandb/wandb/core/internal/timer"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
	"github.com/wandb/wandb/core/internal/watcher"
)

type HandlerOption func(*Handler)

func WithHandlerFwdChannel(fwd chan *pb.Record) HandlerOption {
	return func(h *Handler) {
		h.FwdChan = fwd
	}
}

func WithHandlerOutChannel(out chan *pb.Result) HandlerOption {
	return func(h *Handler) {
		h.OutChan = out
	}
}

func WithHandlerSettings(settings *pb.Settings) HandlerOption {
	return func(h *Handler) {
		h.settings = settings
	}
}

func WithHandlerSystemMonitor(monitor *monitor.SystemMonitor) HandlerOption {
	return func(h *Handler) {
		h.systemMonitor = monitor
	}
}

func WithHandlerWatcher(watcher *watcher.Watcher) HandlerOption {
	return func(h *Handler) {
		h.watcher = watcher
	}
}

func WithHandlerTBHandler(handler *TensorBoard) HandlerOption {
	return func(h *Handler) {
		h.tbHandler = handler
	}
}

func WithHandlerFileHandler(handler *Files) HandlerOption {
	return func(h *Handler) {
		h.filesHandler = handler
	}
}

func WithHandlerFilesInfoHandler(handler *FilesInfo) HandlerOption {
	return func(h *Handler) {
		h.filesInfoHandler = handler
	}
}

func WithHandlerMetricHandler(handler *Metrics) HandlerOption {
	return func(h *Handler) {
		h.metricHandler = handler
	}
}

func WithHandlerSummaryHandler(handler *Summary) HandlerOption {
	return func(h *Handler) {
		h.summaryHandler = handler
	}
}

// Handler is the handler for a stream it handles the incoming messages, processes them
// and passes them to the writer
type Handler struct {
	// ctx is the context for the handler
	ctx context.Context

	// settings is the settings for the handler
	settings *pb.Settings

	// logger is the logger for the handler
	logger *observability.CoreLogger

	// FwdChan is the channel for forwarding messages to the next component
	FwdChan chan *pb.Record

	// OutChan is the channel for sending results to the client
	OutChan chan *pb.Result

	// timer is used to track the run start and execution times
	timer timer.Timer

	// runRecord is the runRecord record received from the server
	runRecord *pb.RunRecord

	// summaryHandler is the summary handler for the stream
	summaryHandler *Summary

	// activeHistory is the history record used to track
	// current active history record for the stream
	activeHistory *ActiveHistory

	// sampledHistory is the sampled history for the stream
	// TODO fix this to be generic type
	sampledHistory map[string]*ReservoirSampling[float32]

	// metricHandler is the metric handler for the stream
	metricHandler *Metrics

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor

	// watcher is the watcher for the stream
	watcher *watcher.Watcher

	// tbHandler is the tensorboard handler
	tbHandler *TensorBoard

	// filesHandler is the file handler for the stream
	filesHandler *Files

	// filesInfoHandler is the file transfer info for the stream
	filesInfoHandler *FilesInfo
}

// NewHandler creates a new handler
func NewHandler(
	ctx context.Context,
	logger *observability.CoreLogger,
	opts ...HandlerOption,
) *Handler {
	h := &Handler{
		ctx:    ctx,
		logger: logger,
	}
	for _, opt := range opts {
		opt(h)
	}
	return h
}

// Do starts the handler
func (h *Handler) Do(inChan <-chan *pb.Record) {
	defer h.logger.Reraise()
	h.logger.Info("handler: started", "stream_id", h.settings.RunId)
	for record := range inChan {
		h.logger.Debug("handling record", "record", record)
		h.handleRecord(record)
	}
	h.Close()
}

func (h *Handler) Close() {
	close(h.OutChan)
	close(h.FwdChan)
	h.logger.Debug("handler: closed", "stream_id", h.settings.RunId)
}

func (h *Handler) sendResponse(record *pb.Record, response *pb.Response) {
	result := &pb.Result{
		ResultType: &pb.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.OutChan <- result
}

func (h *Handler) sendRecordWithControl(record *pb.Record, controlOptions ...func(*pb.Control)) {
	if record == nil {
		return
	}

	if record.GetControl() == nil {
		record.Control = &pb.Control{}
	}

	control := record.GetControl()
	for _, opt := range controlOptions {
		opt(control)
	}
	h.sendRecord(record)
}

func (h *Handler) sendRecord(record *pb.Record) {
	if record == nil {
		return
	}
	h.FwdChan <- record
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *pb.Record) {
	h.summaryHandler.Debounce(h.sendSummary)
	recordType := record.GetRecordType()
	h.logger.Debug("handle: got a message", "record_type", recordType)
	switch x := record.RecordType.(type) {
	case *pb.Record_Alert:
		h.handleAlert(record)
	case *pb.Record_Artifact:
	case *pb.Record_Config:
		h.handleConfig(record)
	case *pb.Record_Exit:
		h.handleExit(record, x.Exit)
	case *pb.Record_Files:
		h.handleFiles(record)
	case *pb.Record_Final:
		h.handleFinal()
	case *pb.Record_Footer:
		h.handleFooter()
	case *pb.Record_Header:
		h.handleHeader(record)
	case *pb.Record_History:
		h.handleHistory(x.History)
	case *pb.Record_LinkArtifact:
		h.handleLinkArtifact(record)
	case *pb.Record_Metric:
		h.handleMetric(record, x.Metric)
	case *pb.Record_Output:
	case *pb.Record_OutputRaw:
		h.handleOutputRaw(record)
	case *pb.Record_Preempting:
		h.handlePreempting(record)
	case *pb.Record_Request:
		h.handleRequest(record)
	case *pb.Record_Run:
		h.handleRun(record)
	case *pb.Record_Stats:
		h.handleSystemMetrics(record)
	case *pb.Record_Summary:
		h.handleSummary(record, x.Summary)
	case *pb.Record_Tbrecord:
		h.handleTBrecord(record)
	case *pb.Record_Telemetry:
		h.handleTelemetry(record)
	case *pb.Record_UseArtifact:
		h.handleUseArtifact(record)
	case nil:
		err := fmt.Errorf("handleRecord: record type is nil")
		h.logger.CaptureFatalAndPanic("error handling record", err)
	default:
		err := fmt.Errorf("handleRecord: unknown record type %T", x)
		h.logger.CaptureFatalAndPanic("error handling record", err)
	}
}

//gocyclo:ignore
func (h *Handler) handleRequest(record *pb.Record) {
	request := record.GetRequest()
	response := &pb.Response{}
	switch x := request.RequestType.(type) {
	case *pb.Request_CheckVersion:
	case *pb.Request_Defer:
		h.handleDefer(record, x.Defer)
		response = nil
	case *pb.Request_GetSummary:
		h.handleGetSummary(record, response)
	case *pb.Request_Keepalive:
	case *pb.Request_NetworkStatus:
	case *pb.Request_PartialHistory:
		h.handlePartialHistory(record, x.PartialHistory)
		response = nil
	case *pb.Request_PollExit:
		h.handlePollExit(record)
		response = nil
	case *pb.Request_RunStart:
		h.handleRunStart(record, x.RunStart)
	case *pb.Request_SampledHistory:
		h.handleSampledHistory(record, response)
	case *pb.Request_ServerInfo:
		h.handleServerInfo(record)
		response = nil
	case *pb.Request_PythonPackages:
		h.handlePythonPackages(record, x.PythonPackages)
		response = nil
	case *pb.Request_Shutdown:
	case *pb.Request_StopStatus:
	case *pb.Request_LogArtifact:
		h.handleLogArtifact(record)
		response = nil
	case *pb.Request_DownloadArtifact:
		h.handleDownloadArtifact(record)
		response = nil
	case *pb.Request_JobInfo:
	case *pb.Request_Attach:
		h.handleAttach(record, response)
	case *pb.Request_Pause:
		h.handlePause()
	case *pb.Request_Resume:
		h.handleResume()
	case *pb.Request_Cancel:
		h.handleCancel(record)
	case *pb.Request_GetSystemMetrics:
		h.handleGetSystemMetrics(record, response)
	case *pb.Request_FileTransferInfo:
		h.handleFileTransferInfo(record)
	case *pb.Request_InternalMessages:
	case *pb.Request_Sync:
		h.handleSync(record)
		response = nil
	case *pb.Request_SenderRead:
		h.handleSenderRead(record)
		response = nil
	default:
		err := fmt.Errorf("handleRequest: unknown request type %T", x)
		h.logger.CaptureFatalAndPanic("error handling request", err)
	}
	if response != nil {
		h.sendResponse(record, response)
	}
}

func (h *Handler) handleDefer(record *pb.Record, request *pb.DeferRequest) {
	switch request.State {
	case pb.DeferRequest_BEGIN:
	case pb.DeferRequest_FLUSH_RUN:
	case pb.DeferRequest_FLUSH_STATS:
		// stop the system monitor to ensure that we don't send any more system metrics
		// after the run has exited
		h.systemMonitor.Stop()
	case pb.DeferRequest_FLUSH_PARTIAL_HISTORY:
		h.activeHistory.Flush()
	case pb.DeferRequest_FLUSH_TB:
		h.tbHandler.Close()
	case pb.DeferRequest_FLUSH_SUM:
		h.handleSummary(nil, &pb.SummaryRecord{})
		h.summaryHandler.Flush(h.sendSummary)
		h.writeAndSendSummaryFile()
	case pb.DeferRequest_FLUSH_DEBOUNCER:
	case pb.DeferRequest_FLUSH_OUTPUT:
	case pb.DeferRequest_FLUSH_JOB:
	case pb.DeferRequest_FLUSH_DIR:
		h.watcher.Close()
	case pb.DeferRequest_FLUSH_FP:
		h.filesHandler.Flush()
	case pb.DeferRequest_JOIN_FP:
	case pb.DeferRequest_FLUSH_FS:
	case pb.DeferRequest_FLUSH_FINAL:
		h.handleFinal()
		h.handleFooter()
	case pb.DeferRequest_END:
	default:
		err := fmt.Errorf("handleDefer: unknown defer state %v", request.State)
		h.logger.CaptureError("unknown defer state", err)
	}
	// Need to clone the record to avoid race condition with the writer
	record = proto.Clone(record).(*pb.Record)
	h.sendRecordWithControl(record,
		func(control *pb.Control) {
			control.AlwaysSend = true
		},
		func(control *pb.Control) {
			control.Local = true
		},
	)
}

func (h *Handler) handleLogArtifact(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleDownloadArtifact(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleLinkArtifact(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handlePollExit(record *pb.Record) {
	result := &pb.Result{
		ResultType: &pb.Result_Response{
			Response: &pb.Response{
				ResponseType: &pb.Response_PollExitResponse{
					PollExitResponse: &pb.PollExitResponse{
						PusherStats: h.filesInfoHandler.GetFilesStats(),
						FileCounts:  h.filesInfoHandler.GetFilesCount(),
						Done:        h.filesInfoHandler.GetDone(),
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	h.OutChan <- result
}

func (h *Handler) handleHeader(record *pb.Record) {
	h.sendRecordWithControl(
		record,
		func(control *pb.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleFinal() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}
	record := &pb.Record{
		RecordType: &pb.Record_Final{
			Final: &pb.FinalRecord{},
		},
	}
	h.sendRecordWithControl(
		record,
		func(control *pb.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleFooter() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}
	record := &pb.Record{
		RecordType: &pb.Record_Footer{
			Footer: &pb.FooterRecord{},
		},
	}
	h.sendRecordWithControl(
		record,
		func(control *pb.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleServerInfo(record *pb.Record) {
	h.sendRecordWithControl(record,
		func(control *pb.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleRunStart(record *pb.Record, request *pb.RunStartRequest) {
	var ok bool
	run := request.Run

	// start the run timer
	h.timer = timer.Timer{}
	startTime := run.StartTime.AsTime()
	h.timer.Start(&startTime)

	if h.runRecord, ok = proto.Clone(run).(*pb.RunRecord); !ok {
		err := fmt.Errorf("handleRunStart: failed to clone run")
		h.logger.CaptureFatalAndPanic("error handling run start", err)
	}
	h.sendRecord(record)

	// start the tensorboard handler
	h.watcher.Start()

	h.filesHandler = h.filesHandler.With(
		WithFilesHandlerHandleFn(h.sendRecord),
	)

	if h.settings.GetConsole().GetValue() != "off" {
		h.filesHandler.Handle(&pb.Record{
			RecordType: &pb.Record_Files{
				Files: &pb.FilesRecord{
					Files: []*pb.FilesItem{
						{
							Path:   consts.OutputFileName,
							Type:   pb.FilesItem_WANDB,
							Policy: pb.FilesItem_END,
						},
					},
				},
			},
		})
	}

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
	metadata := &pb.MetadataRequest{
		Os:       h.settings.GetXOs().GetValue(),
		Python:   h.settings.GetXPython().GetValue(),
		Host:     h.settings.GetHost().GetValue(),
		Cuda:     h.settings.GetXCuda().GetValue(),
		Program:  h.settings.GetProgram().GetValue(),
		CodePath: h.settings.GetProgramAbspath().GetValue(),
		// CodePathLocal: h.settings.GetProgramAbspath().GetValue(),  // todo(launch): add this
		Email:      h.settings.GetEmail().GetValue(),
		Root:       h.settings.GetRootDir().GetValue(),
		Username:   h.settings.GetUsername().GetValue(),
		Docker:     h.settings.GetDocker().GetValue(),
		Executable: h.settings.GetXExecutable().GetValue(),
		Args:       h.settings.GetXArgs().GetValue(),
		Colab:      h.settings.GetColabUrl().GetValue(),
		StartedAt:  run.GetStartTime(),
		Git: &pb.GitRepoRecord{
			RemoteUrl: run.GetGit().GetRemoteUrl(),
			Commit:    run.GetGit().GetCommit(),
		},
	}

	if !h.settings.GetXDisableStats().GetValue() {
		systemInfo := h.systemMonitor.Probe()
		if systemInfo != nil {
			proto.Merge(metadata, systemInfo)
		}
	}
	h.handleMetadata(metadata)
}

func (h *Handler) handlePythonPackages(_ *pb.Record, request *pb.PythonPackagesRequest) {
	// write all requirements to a file
	// send the file as a Files record
	filename := filepath.Join(h.settings.GetFilesDir().GetValue(), consts.RequirementsFileName)
	file, err := os.Create(filename)
	if err != nil {
		h.logger.Error("error creating requirements file", "error", err)
		return
	}
	defer file.Close()

	for _, pkg := range request.Package {
		line := fmt.Sprintf("%s==%s\n", pkg.Name, pkg.Version)
		_, err := file.WriteString(line)
		if err != nil {
			h.logger.Error("error writing requirements file", "error", err)
			return
		}
	}
	record := &pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: []*pb.FilesItem{
					{
						Path: consts.RequirementsFileName,
						Type: pb.FilesItem_WANDB,
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
		if err = fileslib.CopyFile(programAbsolute, savedProgram); err != nil {
			return
		}
	}
	record := &pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: []*pb.FilesItem{
					{
						Path: filepath.Join("code", programRelative),
						Type: pb.FilesItem_WANDB,
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

	git := gitlib.NewGit(h.settings.GetRootDir().GetValue(), h.logger)
	if !git.IsAvailable() {
		return
	}

	files := []*pb.FilesItem{}

	filesDirPath := h.settings.GetFilesDir().GetValue()
	file := filepath.Join(filesDirPath, consts.DiffFileName)
	if err := git.SavePatch("HEAD", file); err != nil {
		h.logger.Info("error generating local diff", "error", err)
	} else {
		files = append(files, &pb.FilesItem{Path: consts.DiffFileName, Type: pb.FilesItem_WANDB})
	}

	if output, err := git.LatestCommit("@{u}"); err != nil {
		h.logger.Info("error getting latest remote commit", "error", err, "output", output)
	} else {
		diffFileName := fmt.Sprintf("diff_%s.patch", output)
		file = filepath.Join(filesDirPath, diffFileName)
		if err := git.SavePatch("@{u}", file); err != nil {
			h.logger.Info("error generating remote diff", "error", err)
		} else {
			files = append(files, &pb.FilesItem{Path: diffFileName, Type: pb.FilesItem_WANDB})
		}
	}

	if len(files) == 0 {
		return
	}

	record := &pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: files,
			},
		},
	}
	h.handleFiles(record)
}

func (h *Handler) handleMetadata(request *pb.MetadataRequest) {
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
	filePath := filepath.Join(h.settings.GetFilesDir().GetValue(), consts.MetaFileName)
	if err := os.WriteFile(filePath, jsonBytes, 0644); err != nil {
		h.logger.CaptureError("error writing metadata file", err)
		return
	}

	record := &pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: []*pb.FilesItem{
					{
						Path: consts.MetaFileName,
						Type: pb.FilesItem_WANDB,
					},
				},
			},
		},
	}

	h.handleFiles(record)
}

func (h *Handler) handleAttach(_ *pb.Record, response *pb.Response) {

	response.ResponseType = &pb.Response_AttachResponse{
		AttachResponse: &pb.AttachResponse{
			Run: h.runRecord,
		},
	}
}

func (h *Handler) handleCancel(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handlePause() {
	h.timer.Pause()
	h.systemMonitor.Stop()
}

func (h *Handler) handleResume() {
	h.timer.Resume()
	h.systemMonitor.Do()
}

func (h *Handler) handleSystemMetrics(record *pb.Record) {
	h.sendRecord(record)
}

// handleStepMetric handles the step metric for a given metric key. If the step metric is not
// defined, it will be added to the defined metrics map.
func (h *Handler) handleStepMetric(key string) {
	if key == "" {
		return
	}

	// already exists no need to add
	if _, defined := h.metricHandler.Defined[key]; defined {
		return
	}

	metric, err := AddMetric(key, key, &h.metricHandler.Defined)

	if err != nil {
		h.logger.CaptureError("error adding metric to map", err)
		return
	}

	stepRecord := &pb.Record{
		RecordType: &pb.Record_Metric{
			Metric: metric,
		},
		Control: &pb.Control{
			Local: true,
		},
	}
	h.sendRecord(stepRecord)
}

func (h *Handler) handleMetric(record *pb.Record, metric *pb.MetricRecord) {
	// metric can have a glob name or a name
	// TODO: replace glob-name/name with one-of field
	switch {
	case metric.GetGlobName() != "":
		if _, err := AddMetric(metric, metric.GetGlobName(), &h.metricHandler.Glob); err != nil {
			h.logger.CaptureError("error adding metric to map", err)
			return
		}
		h.sendRecord(record)
	case metric.GetName() != "":
		if _, err := AddMetric(metric, metric.GetName(), &h.metricHandler.Defined); err != nil {
			h.logger.CaptureError("error adding metric to map", err)
			return
		}
		h.handleStepMetric(metric.GetStepMetric())
		h.sendRecord(record)
	default:
		h.logger.CaptureError("invalid metric", errors.New("invalid metric"))
	}
}

func (h *Handler) handleOutputRaw(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handlePreempting(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleRun(record *pb.Record) {
	h.sendRecordWithControl(record,
		func(control *pb.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleConfig(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleAlert(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleExit(record *pb.Record, exit *pb.RunExitRecord) {
	// stop the run timer and set the runtime
	h.timer.Pause()
	runtime := int32(h.timer.Elapsed().Seconds())
	exit.Runtime = runtime

	// update summary with runtime
	if !h.settings.GetXSync().GetValue() {
		summaryRecord := corelib.ConsolidateSummaryItems(h.summaryHandler.Consolidated, []*pb.SummaryItem{
			{
				Key: "_wandb", ValueJson: fmt.Sprintf(`{"runtime": %d}`, runtime),
			},
		})
		h.summaryHandler.UpdateDelta(summaryRecord)
	}

	// send the exit record
	h.sendRecordWithControl(record,
		func(control *pb.Control) {
			control.AlwaysSend = true
			// do not write to the transaction log when syncing an offline run
			if h.settings.GetXSync().GetValue() {
				control.Local = true
			}
		},
	)
}

func (h *Handler) handleFiles(record *pb.Record) {
	if record.GetFiles() == nil {
		return
	}
	h.filesHandler.Handle(record)
}

func (h *Handler) handleGetSummary(_ *pb.Record, response *pb.Response) {
	var items []*pb.SummaryItem

	for key, element := range h.summaryHandler.Consolidated {
		items = append(items, &pb.SummaryItem{Key: key, ValueJson: element})
	}
	response.ResponseType = &pb.Response_GetSummaryResponse{
		GetSummaryResponse: &pb.GetSummaryResponse{
			Item: items,
		},
	}
}

func (h *Handler) handleGetSystemMetrics(_ *pb.Record, response *pb.Response) {
	sm := h.systemMonitor.GetBuffer()

	response.ResponseType = &pb.Response_GetSystemMetricsResponse{
		GetSystemMetricsResponse: &pb.GetSystemMetricsResponse{
			SystemMetrics: make(map[string]*pb.SystemMetricsBuffer),
		},
	}

	for key, samples := range sm {
		buffer := make([]*pb.SystemMetricSample, 0, len(samples.GetElements()))

		// convert samples to buffer:
		for _, sample := range samples.GetElements() {
			buffer = append(buffer, &pb.SystemMetricSample{
				Timestamp: sample.Timestamp,
				Value:     float32(sample.Value),
			})
		}
		// add to response as map key: buffer
		response.GetGetSystemMetricsResponse().SystemMetrics[key] = &pb.SystemMetricsBuffer{
			Record: buffer,
		}
	}
}

func (h *Handler) handleFileTransferInfo(record *pb.Record) {
	h.filesInfoHandler.Handle(record)
}

func (h *Handler) handleSync(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleSenderRead(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleTelemetry(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleUseArtifact(record *pb.Record) {
	h.sendRecord(record)
}

func (h *Handler) writeAndSendSummaryFile() {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	// write summary to file
	summaryFile := filepath.Join(h.settings.GetFilesDir().GetValue(), consts.SummaryFileName)

	jsonBytes, err := json.MarshalIndent(h.summaryHandler.Consolidated, "", "  ")
	if err != nil {
		h.logger.Error("handler: writeAndSendSummaryFile: error marshalling summary", "error", err)
		return
	}

	if err := os.WriteFile(summaryFile, []byte(jsonBytes), 0644); err != nil {
		h.logger.Error("handler: writeAndSendSummaryFile: failed to write config file", "error", err)
	}

	// send summary file
	h.filesHandler.Handle(&pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: []*pb.FilesItem{
					{
						Path: consts.SummaryFileName,
						Type: pb.FilesItem_WANDB,
					},
				},
			},
		},
	})
}

func (h *Handler) sendSummary() {
	summaryRecord := &pb.SummaryRecord{
		Update: []*pb.SummaryItem{},
	}

	for key, value := range h.summaryHandler.Delta {
		summaryRecord.Update = append(summaryRecord.Update, &pb.SummaryItem{
			Key: key, ValueJson: value,
		})
	}

	record := &pb.Record{
		RecordType: &pb.Record_Summary{
			Summary: summaryRecord,
		},
	}
	h.sendRecord(record)
	// reset delta summary
	clear(h.summaryHandler.Delta)
}

func (h *Handler) handleSummary(_ *pb.Record, summary *pb.SummaryRecord) {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	runtime := int32(h.timer.Elapsed().Seconds())

	// update summary with runtime
	summary.Update = append(summary.Update, &pb.SummaryItem{
		Key: "_wandb", ValueJson: fmt.Sprintf(`{"runtime": %d}`, runtime),
	})

	summaryRecord := corelib.ConsolidateSummaryItems(h.summaryHandler.Consolidated, summary.Update)
	h.summaryHandler.UpdateDelta(summaryRecord)
}

func (h *Handler) handleTBrecord(record *pb.Record) {
	err := h.tbHandler.Handle(record)
	if err != nil {
		h.logger.CaptureError("error handling tbrecord", err)
	}
}

func (h *Handler) GetRun() *pb.RunRecord {
	return h.runRecord
}
