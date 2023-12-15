package server

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/pkg/monitor"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	summaryDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	summaryDebouncerBurstSize = 1        // todo: audit burst size
)

type HandlerOption func(*Handler)

func WithHandlerFwdChannel(fwd chan *service.Record) HandlerOption {
	return func(h *Handler) {
		h.fwdChan = fwd
	}
}

func WithHandlerOutChannel(out chan *service.Result) HandlerOption {
	return func(h *Handler) {
		h.outChan = out
	}
}

func WithHandlerSettings(settings *service.Settings) HandlerOption {
	return func(h *Handler) {
		h.settings = settings
	}
}

func WithHandlerSystemMonitor(monitor *monitor.SystemMonitor) HandlerOption {
	return func(h *Handler) {
		h.systemMonitor = monitor
	}
}

func WithHandlerFileHandler(handler *FileHandler) HandlerOption {
	return func(h *Handler) {
		h.fileHandler = handler
	}
}

func WithHandlerFileTransferHandler(handler *FileTransferHandler) HandlerOption {
	return func(h *Handler) {
		h.fileTransferHandler = handler
	}
}

func WithHandlerMetricHandler(handler *MetricHandler) HandlerOption {
	return func(h *Handler) {
		h.metricHandler = handler
	}
}

func WithHandlerSummaryHandler(handler *SummaryHandler) HandlerOption {
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
	settings *service.Settings

	// logger is the logger for the handler
	logger *observability.CoreLogger

	// fwdChan is the channel for forwarding messages to the next component
	fwdChan chan *service.Record

	// outChan is the channel for sending results to the client
	outChan chan *service.Result

	// timer is used to track the run start and execution times
	timer Timer

	// runRecord is the runRecord record received from the server
	runRecord *service.RunRecord

	// summaryHandler is the summary handler for the stream
	summaryHandler *SummaryHandler

	// activeHistory is the history record used to track
	// current active history record for the stream
	activeHistory *ActiveHistory

	// sampledHistory is the sampled history for the stream
	// TODO fix this to be generic type
	sampledHistory map[string]*ReservoirSampling[float32]

	// metricHandler is the metric handler for the stream
	metricHandler *MetricHandler

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor

	// fileHandler is the file handler for the stream
	fileHandler *FileHandler

	// fileTransferHandler is the file transfer info for the stream
	fileTransferHandler *FileTransferHandler
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
func (h *Handler) Do(inChan <-chan *service.Record) {
	defer h.logger.Reraise()
	h.logger.Info("handler: started", "stream_id", h.settings.RunId)
	for record := range inChan {
		h.logger.Debug("handling record", "record", record)
		h.handleRecord(record)
	}
	h.Close()
}

func (h *Handler) Close() {
	close(h.outChan)
	close(h.fwdChan)
	h.logger.Debug("handler: closed", "stream_id", h.settings.RunId)
}

func (h *Handler) sendResponse(record *service.Record, response *service.Response) {
	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.outChan <- result
}

func (h *Handler) sendRecordWithControl(record *service.Record, controlOptions ...func(*service.Control)) {
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
	h.sendRecord(record)
}

func (h *Handler) sendRecord(record *service.Record) {
	if record == nil {
		return
	}
	h.fwdChan <- record
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *service.Record) {
	h.summaryHandler.Debounce(h.sendSummary)
	recordType := record.GetRecordType()
	h.logger.Debug("handle: got a message", "record_type", recordType)
	switch x := record.RecordType.(type) {
	case *service.Record_Alert:
		h.handleAlert(record)
	case *service.Record_Artifact:
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
	case *service.Record_OutputRaw:
		h.handleOutputRaw(record)
	case *service.Record_Preempting:
		h.handlePreempting(record)
	case *service.Record_Request:
		h.handleRequest(record)
	case *service.Record_Run:
		h.handleRun(record)
	case *service.Record_StreamTable:
		h.handleStreamTable(record)
	case *service.Record_StreamData:
		h.handleStreamData(record)
	case *service.Record_Stats:
		h.handleSystemMetrics(record)
	case *service.Record_Summary:
		h.handleSummary(record, x.Summary)
	case *service.Record_Tbrecord:
	case *service.Record_Telemetry:
		h.handleTelemetry(record)
	case *service.Record_UseArtifact:
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
func (h *Handler) handleRequest(record *service.Record) {
	request := record.GetRequest()
	response := &service.Response{}
	switch x := request.RequestType.(type) {
	case *service.Request_CheckVersion:
	case *service.Request_Defer:
		h.handleDefer(record, x.Defer)
		return
	case *service.Request_GetSummary:
		h.handleGetSummary(record, response)
	case *service.Request_Keepalive:
	case *service.Request_NetworkStatus:
	case *service.Request_PartialHistory:
		h.handlePartialHistory(record, x.PartialHistory)
		return
	case *service.Request_PollExit:
		h.handlePollExit(record)
		return
	case *service.Request_RunStart:
		h.handleRunStart(record, x.RunStart)
	case *service.Request_SampledHistory:
		h.handleSampledHistory(record, response)
	case *service.Request_ServerInfo:
		h.handleServerInfo(record)
		response = nil
	case *service.Request_Shutdown:
	case *service.Request_StopStatus:
	case *service.Request_LogArtifact:
		h.handleLogArtifact(record)
		response = nil
	case *service.Request_DownloadArtifact:
		h.handleDownloadArtifact(record)
		response = nil
	case *service.Request_JobInfo:
	case *service.Request_Attach:
		h.handleAttach(record, response)
	case *service.Request_Pause:
		h.handlePause()
	case *service.Request_Resume:
		h.handleResume()
	case *service.Request_Cancel:
		h.handleCancel(record)
	case *service.Request_GetSystemMetrics:
		h.handleGetSystemMetrics(record, response)
	case *service.Request_FileTransferInfo:
		h.handleFileTransferInfo(record)
	case *service.Request_InternalMessages:
	case *service.Request_Sync:
		h.handleSync(record)
		response = nil
	case *service.Request_SenderRead:
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

func (h *Handler) handleDefer(record *service.Record, request *service.DeferRequest) {
	switch request.State {
	case service.DeferRequest_BEGIN:
	case service.DeferRequest_FLUSH_RUN:
	case service.DeferRequest_FLUSH_STATS:
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		h.activeHistory.Flush()
	case service.DeferRequest_FLUSH_TB:
	case service.DeferRequest_FLUSH_SUM:
		h.handleSummary(nil, &service.SummaryRecord{})
		h.summaryHandler.Flush(h.sendSummary)
	case service.DeferRequest_FLUSH_DEBOUNCER:
	case service.DeferRequest_FLUSH_OUTPUT:
	case service.DeferRequest_FLUSH_JOB:
	case service.DeferRequest_FLUSH_DIR:
		rec := h.fileHandler.Final()
		h.sendRecord(rec)
	case service.DeferRequest_FLUSH_FP:
	case service.DeferRequest_JOIN_FP:
		h.fileHandler.Close()
	case service.DeferRequest_FLUSH_FS:
	case service.DeferRequest_FLUSH_FINAL:
		h.handleFinal()
		h.handleFooter()
	case service.DeferRequest_END:
	default:
		err := fmt.Errorf("handleDefer: unknown defer state %v", request.State)
		h.logger.CaptureError("unknown defer state", err)
	}
	// Need to clone the record to avoid race condition with the writer
	record = proto.Clone(record).(*service.Record)
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
		func(control *service.Control) {
			control.Local = true
		},
	)
}

func (h *Handler) handleLogArtifact(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleDownloadArtifact(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleLinkArtifact(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handlePollExit(record *service.Record) {
	result := &service.Result{
		ResultType: &service.Result_Response{
			Response: &service.Response{
				ResponseType: &service.Response_PollExitResponse{
					PollExitResponse: &service.PollExitResponse{
						PusherStats: &service.FilePusherStats{
							UploadedBytes: h.fileTransferHandler.GetUploadedBytes(),
							TotalBytes:    h.fileTransferHandler.GetTotalBytes(),
							DedupedBytes:  h.fileTransferHandler.GetDedupedBytes(),
						},
						FileCounts: h.fileTransferHandler.GetFileCounts(),
						Done:       h.fileTransferHandler.IsDone(),
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	h.outChan <- result
}

func (h *Handler) handleHeader(record *service.Record) {
	h.sendRecordWithControl(
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
	h.sendRecordWithControl(
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
	h.sendRecordWithControl(
		record,
		func(control *service.Control) {
			control.AlwaysSend = false
		},
	)
}

func (h *Handler) handleServerInfo(record *service.Record) {
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleRunStart(record *service.Record, request *service.RunStartRequest) {
	var ok bool
	run := request.Run

	// start the run timer
	h.timer = Timer{}
	startTime := run.StartTime.AsTime()
	h.timer.Start(&startTime)

	if h.runRecord, ok = proto.Clone(run).(*service.RunRecord); !ok {
		err := fmt.Errorf("handleRunStart: failed to clone run")
		h.logger.CaptureFatalAndPanic("error handling run start", err)
	}
	h.sendRecord(record)

	h.fileHandler.Start()

	h.handleCodeSave()

	// NOTE: once this request arrives in the sender,
	// the latter will start its filestream and uploader
	// initialize the run metadata from settings

	metadata := &service.MetadataRequest{
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
		Git: &service.GitRepoRecord{
			RemoteUrl: run.GetGit().GetRemoteUrl(),
			Commit:    run.GetGit().GetCommit(),
		},
	}

	// start the system monitor
	if !h.settings.GetXDisableStats().GetValue() {
		h.systemMonitor.Do()
		systemInfo := h.systemMonitor.Probe()
		if systemInfo != nil {
			proto.Merge(metadata, systemInfo)
		}
	}

	h.handleMetadata(metadata)
}

func (h *Handler) handleAttach(_ *service.Record, response *service.Response) {

	response.ResponseType = &service.Response_AttachResponse{
		AttachResponse: &service.AttachResponse{
			Run: h.runRecord,
		},
	}
}

func (h *Handler) handleCancel(record *service.Record) {
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

func (h *Handler) handleCodeSave() {
	if !h.settings.GetSaveCode().GetValue() {
		return
	}

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
		if err = copyFile(programAbsolute, savedProgram); err != nil {
			return
		}
	}
	record := service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: filepath.Join("code", programRelative),
					},
				},
			},
		},
	}
	h.handleFiles(&record)
}

func (h *Handler) handleMetadata(request *service.MetadataRequest) {
	// TODO: Sending metadata as a request for now, eventually this should be turned into
	//  a record and stored in the transaction log
	if h.settings.GetXDisableMeta().GetValue() {
		return
	}

	record := service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_Metadata{
					Metadata: request,
				},
			},
		},
	}
	h.sendRecordWithControl(&record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleSystemMetrics(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleOutputRaw(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handlePreempting(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleRun(record *service.Record) {
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleConfig(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleAlert(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleExit(record *service.Record, exit *service.RunExitRecord) {
	// stop the system monitor to ensure that we don't send any more system metrics
	// after the run has exited
	h.systemMonitor.Stop()

	// stop the run timer and set the runtime
	h.timer.Pause()
	runtime := int32(h.timer.Elapsed().Seconds())
	exit.Runtime = runtime

	// update summary with runtime
	if !h.settings.GetXSync().GetValue() {
		summaryRecord := corelib.ConsolidateSummaryItems(h.summaryHandler.consolidatedSummary, []*service.SummaryItem{
			{
				Key: "_wandb", ValueJson: fmt.Sprintf(`{"runtime": %d}`, runtime),
			},
		})
		h.summaryHandler.updateSummaryDelta(summaryRecord)
	}

	// send the exit record
	h.sendRecordWithControl(record,
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

	rec := h.fileHandler.Handle(record)
	h.sendRecord(rec)
}

func (h *Handler) handleGetSummary(_ *service.Record, response *service.Response) {
	var items []*service.SummaryItem

	for key, element := range h.summaryHandler.consolidatedSummary {
		items = append(items, &service.SummaryItem{Key: key, ValueJson: element})
	}
	response.ResponseType = &service.Response_GetSummaryResponse{
		GetSummaryResponse: &service.GetSummaryResponse{
			Item: items,
		},
	}
}

func (h *Handler) handleGetSystemMetrics(_ *service.Record, response *service.Response) {
	sm := h.systemMonitor.GetBuffer()

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
}

func (h *Handler) handleFileTransferInfo(record *service.Record) {
	info := record.GetRequest().GetFileTransferInfo()
	h.fileTransferHandler.Handle(info)
}

func (h *Handler) handleSync(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleSenderRead(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleTelemetry(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleUseArtifact(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) sendSummary() {
	summaryRecord := &service.SummaryRecord{
		Update: []*service.SummaryItem{},
	}

	for key, value := range h.summaryHandler.summaryDelta {
		summaryRecord.Update = append(summaryRecord.Update, &service.SummaryItem{
			Key: key, ValueJson: value,
		})
	}
	record := &service.Record{
		RecordType: &service.Record_Summary{
			Summary: summaryRecord,
		},
	}
	h.sendRecord(record)
	// reset delta summary
	clear(h.summaryHandler.summaryDelta)
}

func (h *Handler) handleSummary(_ *service.Record, summary *service.SummaryRecord) {
	if h.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	runtime := int32(h.timer.Elapsed().Seconds())

	// update summary with runtime
	summary.Update = append(summary.Update, &service.SummaryItem{
		Key: "_wandb", ValueJson: fmt.Sprintf(`{"runtime": %d}`, runtime),
	})

	summaryRecord := corelib.ConsolidateSummaryItems(h.summaryHandler.consolidatedSummary, summary.Update)
	h.summaryHandler.updateSummaryDelta(summaryRecord)
}

func (h *Handler) GetRun() *service.RunRecord {
	return h.runRecord
}

func (h *Handler) handleStreamTable(record *service.Record) {
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleStreamData(record *service.Record) {
	h.sendRecord(record)
}
