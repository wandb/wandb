package server

import (
	"context"
	"fmt"
	"time"

	"github.com/wandb/wandb/nexus/pkg/monitor"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// Timer is used to track the run start and execution times
type Timer struct {
	startTime   time.Time
	resumeTime  time.Time
	accumulated time.Duration
	isStarted   bool
	isPaused    bool
}

func (t *Timer) GetStartTimeMicro() float64 {
	return float64(t.startTime.UnixMicro()) / 1e6
}

func (t *Timer) Start(startTime *time.Time) {
	if startTime != nil {
		t.startTime = *startTime
	} else {
		t.startTime = time.Now()
	}
	t.resumeTime = t.startTime
	t.isStarted = true
}

func (t *Timer) Pause() {
	if !t.isPaused {
		elapsed := time.Since(t.resumeTime)
		t.accumulated += elapsed
		t.isPaused = true
	}
}

func (t *Timer) Resume() {
	if t.isPaused {
		t.resumeTime = time.Now()
		t.isPaused = false
	}
}

func (t *Timer) Elapsed() time.Duration {
	if !t.isStarted {
		return 0
	}
	if t.isPaused {
		return t.accumulated
	}
	return t.accumulated + time.Since(t.resumeTime)
}

// Handler is the handler for a stream
// it handles the incoming messages, processes them
// and passes them to the writer
type Handler struct {
	// ctx is the context for the handler
	ctx context.Context

	// settings is the settings for the handler
	settings *service.Settings

	// logger is the logger for the handler
	logger *observability.NexusLogger

	// recordChan is the channel for further processing
	// of the incoming messages, by the writer
	recordChan chan *service.Record

	// resultChan is the channel for returning results
	// to the client
	resultChan chan *service.Result

	// timer is used to track the run start and execution times
	timer Timer

	// runRecord is the runRecord record received
	// from the server
	runRecord *service.RunRecord

	// consolidatedSummary is the full summary (all keys)
	// TODO(memory): persist this in the future as it will grow with number of distinct keys
	consolidatedSummary map[string]string

	// historyRecord is the history record used to track
	// current active history record for the stream
	historyRecord *service.HistoryRecord

	// mh is the metric handler for the stream
	mh *MetricHandler

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor
}

// NewHandler creates a new handler
func NewHandler(
	ctx context.Context,
	settings *service.Settings,
	logger *observability.NexusLogger,
) *Handler {
	// init the system monitor if stats are enabled
	h := &Handler{
		ctx:                 ctx,
		settings:            settings,
		logger:              logger,
		consolidatedSummary: make(map[string]string),
		recordChan:          make(chan *service.Record, BufferSize),
		resultChan:          make(chan *service.Result, BufferSize),
	}
	if !settings.GetXDisableStats().GetValue() {
		h.systemMonitor = monitor.NewSystemMonitor(settings, logger)
	}
	return h
}

// do this starts the handler
func (h *Handler) do(inChan <-chan *service.Record) {
	defer observability.Reraise()

	h.logger.Info("handler: started", "stream_id", h.settings.RunId)
	for record := range inChan {
		h.handleRecord(record)
	}
	h.close()
	h.logger.Debug("handler: closed", "stream_id", h.settings.RunId)
}

func (h *Handler) sendResponse(record *service.Record, response *service.Response) {
	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.resultChan <- result
}

func (h *Handler) close() {
	close(h.resultChan)
	close(h.recordChan)
}

func (h *Handler) sendRecordWithControl(record *service.Record, controlOptions ...func(*service.Control)) {
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
	h.recordChan <- record
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *service.Record) {
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
		h.handleFinal(record)
	case *service.Record_Footer:
	case *service.Record_Header:
	case *service.Record_History:
	case *service.Record_LinkArtifact:
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
	case *service.Record_Stats:
		h.handleSystemMetrics(record)
	case *service.Record_Summary:
		h.handleSummary(record, x.Summary)
	case *service.Record_Tbrecord:
	case *service.Record_Telemetry:
		h.handleTelemetry(record)
	case nil:
		err := fmt.Errorf("handleRecord: record type is nil")
		h.logger.CaptureFatalAndPanic("error handling record", err)
	default:
		err := fmt.Errorf("handleRecord: unknown record type %T", x)
		h.logger.CaptureFatalAndPanic("error handling record", err)
	}
}

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
	case *service.Request_RunStart:
		h.handleRunStart(record, x.RunStart)
	case *service.Request_SampledHistory:
	case *service.Request_ServerInfo:
		h.handleServerInfo(record)
	case *service.Request_Shutdown:
	case *service.Request_StopStatus:
	case *service.Request_LogArtifact:
		h.handleLogArtifact(record, x.LogArtifact, response)
	case *service.Request_JobInfo:
	case *service.Request_Attach:
		h.handleAttach(record, response)
	case *service.Request_Pause:
		h.handlePause()
	case *service.Request_Resume:
		h.handleResume()
	case *service.Request_Cancel:
		h.handleCancel(record)
	default:
		err := fmt.Errorf("handleRequest: unknown request type %T", x)
		h.logger.CaptureFatalAndPanic("error handling request", err)
	}
	h.sendResponse(record, response)
}

func (h *Handler) handleDefer(record *service.Record, request *service.DeferRequest) {
	switch request.State {
	case service.DeferRequest_BEGIN:
	case service.DeferRequest_FLUSH_RUN:
	case service.DeferRequest_FLUSH_STATS:
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		h.handleHistory(h.historyRecord)
	case service.DeferRequest_FLUSH_TB:
	case service.DeferRequest_FLUSH_SUM:
		h.handleSummary(nil, &service.SummaryRecord{})
	case service.DeferRequest_FLUSH_DEBOUNCER:
	case service.DeferRequest_FLUSH_OUTPUT:
	case service.DeferRequest_FLUSH_JOB:
	case service.DeferRequest_FLUSH_DIR:
	case service.DeferRequest_FLUSH_FP:
	case service.DeferRequest_JOIN_FP:
	case service.DeferRequest_FLUSH_FS:
	case service.DeferRequest_FLUSH_FINAL:
	case service.DeferRequest_END:
	default:
		err := fmt.Errorf("handleDefer: unknown defer state %v", request.State)
		h.logger.CaptureError("unknown defer state", err)
	}
	// Need to clone the record to avoide race condition with the writer
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

func (h *Handler) handleLogArtifact(record *service.Record, _ *service.LogArtifactRequest, _ *service.Response) {
	h.sendRecord(record)
}

// startSystemMonitor starts the system monitor
func (h *Handler) startSystemMonitor() {
	if h.systemMonitor == nil {
		return
	}
	go func() {
		// this goroutine reads from the system monitor channel and writes
		// to the handler's record channel. it will exit when the system
		// monitor channel is closed
		for msg := range h.systemMonitor.OutChan {
			h.recordChan <- msg
		}
		h.logger.Debug("system monitor channel closed")
	}()
	h.systemMonitor.Do()
}

func (h *Handler) handlePollExit(record *service.Record) {
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleFinal(record *service.Record) {
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
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

	// NOTE: once this request arrives in the sender,
	// the latter will start its filestream and uploader

	// TODO: this is a hack, we should not be sending metadata from here,
	//  it should arrive as a proper request from the client.
	//  attempting to do this before the run start request arrives in the sender
	//  will cause a segfault because the sender's uploader is not initialized yet.
	h.handleMetadata(record, request)

	// start the system monitor
	h.startSystemMonitor()
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
	h.startSystemMonitor()
}

func (h *Handler) handleMetadata(_ *service.Record, req *service.RunStartRequest) {
	// Sending metadata as a request for now, eventually this should be turned into
	// a record and stored in the transaction log
	record := &service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{RequestType: &service.Request_Metadata{
				Metadata: &service.MetadataRequest{
					Os:         h.settings.GetXOs().GetValue(),
					Python:     h.settings.GetXPython().GetValue(),
					Host:       h.settings.GetHost().GetValue(),
					Cuda:       h.settings.GetXCuda().GetValue(),
					Program:    h.settings.GetProgram().GetValue(),
					Email:      h.settings.GetEmail().GetValue(),
					Root:       h.settings.GetRootDir().GetValue(),
					Username:   h.settings.GetUsername().GetValue(),
					Docker:     h.settings.GetDocker().GetValue(),
					Executable: h.settings.GetXExecutable().GetValue(),
					Args:       h.settings.GetXArgs().GetValue(),
					StartedAt:  req.Run.StartTime,
				}}}}}
	h.sendRecord(record)
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
	h.sendRecord(record)
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

	// send the exit record
	h.sendRecordWithControl(record,
		func(control *service.Control) {
			control.AlwaysSend = true
		},
	)
}

func (h *Handler) handleFiles(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleGetSummary(_ *service.Record, response *service.Response) {
	var items []*service.SummaryItem

	for key, element := range h.consolidatedSummary {
		items = append(items, &service.SummaryItem{Key: key, ValueJson: element})
	}
	response.ResponseType = &service.Response_GetSummaryResponse{
		GetSummaryResponse: &service.GetSummaryResponse{
			Item: items,
		},
	}
}

func (h *Handler) handleTelemetry(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleSummary(_ *service.Record, summary *service.SummaryRecord) {

	runtime := int32(h.timer.Elapsed().Seconds())

	// update summary with runtime
	summary.Update = append(summary.Update, &service.SummaryItem{
		Key: "_wandb", ValueJson: fmt.Sprintf(`{"runtime": %d}`, runtime),
	})

	summaryRecord := nexuslib.ConsolidateSummaryItems(h.consolidatedSummary, summary.Update)
	h.sendRecord(summaryRecord)
}

func (h *Handler) GetRun() *service.RunRecord {
	return h.runRecord
}
