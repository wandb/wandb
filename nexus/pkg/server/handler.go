package server

import (
	"context"
	"fmt"
	"strconv"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/monitor"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// Handler is the handler for a stream
// it handles the incoming messages process them
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

	// startTime is the start time
	startTime float64

	// runRecord is the runRecord record received
	// from the server
	runRecord *service.RunRecord

	// consolidatedSummary is the full summary (all keys)
	// TODO(memory): persist this in the future as it will grow with number of distinct keys
	consolidatedSummary map[string]string

	// historyRecord is the history record used to track
	// current active history record for the stream
	historyRecord *service.HistoryRecord

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor
}

// NewHandler creates a new handler
func NewHandler(
	ctx context.Context,
	settings *service.Settings,
	logger *observability.NexusLogger,
	systemMonitor *monitor.SystemMonitor,
) *Handler {
	h := &Handler{
		ctx:                 ctx,
		settings:            settings,
		logger:              logger,
		systemMonitor:       systemMonitor,
		consolidatedSummary: make(map[string]string),
	}
	return h
}

// do this starts the handler
func (h *Handler) do(inChan <-chan *service.Record) (<-chan *service.Record, <-chan *service.Result) {
	defer observability.Reraise()

	h.logger.Info("handler: started", "stream_id", h.settings.RunId)

	h.recordChan = make(chan *service.Record, BufferSize)
	h.resultChan = make(chan *service.Result, BufferSize)

	go func() {
		for record := range inChan {
			h.handleRecord(record)
		}
		close(h.recordChan)
		close(h.resultChan)
		h.logger.Debug("handler: closed", "stream_id", h.settings.RunId)
	}()
	return h.recordChan, h.resultChan
}

func (h *Handler) sendResponse(record *service.Record, response *service.Response) {
	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.resultChan <- result
}

func (h *Handler) sendRecord(record *service.Record) {
	control := record.GetControl()
	if control != nil {
		control.AlwaysSend = true
	}
	h.recordChan <- record
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *service.Record) {
	h.logger.Debug("handle: got a message", "record", record)
	switch x := record.RecordType.(type) {
	case *service.Record_Alert:
		h.handleAlert(record)
	case *service.Record_Artifact:
	case *service.Record_Config:
		h.handleConfig(record)
	case *service.Record_Exit:
		h.handleExit(record)
	case *service.Record_Files:
		h.handleFiles(record)
	case *service.Record_Final:
	case *service.Record_Footer:
	case *service.Record_Header:
	case *service.Record_History:
	case *service.Record_LinkArtifact:
	case *service.Record_Metric:
	case *service.Record_Output:
	case *service.Record_OutputRaw:
		h.handleOutputRaw(record)
	case *service.Record_Preempting:
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
		h.handleDefer(record)
	case *service.Request_GetSummary:
		h.handleGetSummary(record, response)
	case *service.Request_Keepalive:
	case *service.Request_NetworkStatus:
	case *service.Request_PartialHistory:
		h.handlePartialHistory(record, x.PartialHistory)
		return
	case *service.Request_PollExit:
	case *service.Request_RunStart:
		h.handleRunStart(record, x.RunStart)
	case *service.Request_SampledHistory:
	case *service.Request_ServerInfo:
	case *service.Request_Shutdown:
	case *service.Request_StopStatus:
	case *service.Request_LogArtifact:
		h.handleLogArtifact(record, x.LogArtifact, response)
	case *service.Request_JobInfo:
	case *service.Request_Attach:
		h.handleAttach(record, response)
	default:
		err := fmt.Errorf("handleRequest: unknown request type %T", x)
		h.logger.CaptureFatalAndPanic("error handling request", err)
	}
	h.sendResponse(record, response)
}

func (h *Handler) handleDefer(record *service.Record) {
	request := record.GetRequest().GetDefer()
	switch request.State {
	case service.DeferRequest_BEGIN:
	case service.DeferRequest_FLUSH_STATS:
		h.systemMonitor.Stop()
	case service.DeferRequest_FLUSH_PARTIAL_HISTORY:
		h.flushHistory(h.historyRecord)
	case service.DeferRequest_FLUSH_TB:
	case service.DeferRequest_FLUSH_SUM:
	case service.DeferRequest_FLUSH_DEBOUNCER:
	case service.DeferRequest_FLUSH_OUTPUT:
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
	h.sendRecord(record)
}

func (h *Handler) handleLogArtifact(record *service.Record, msg *service.LogArtifactRequest, resp *service.Response) {
	h.sendRecord(record)
}

func (h *Handler) handleRunStart(record *service.Record, request *service.RunStartRequest) {
	var ok bool
	run := request.Run

	h.startTime = float64(run.StartTime.AsTime().UnixMicro()) / 1e6
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
	h.systemMonitor.Do()
}

func (h *Handler) handleAttach(_ *service.Record, response *service.Response) {

	response.ResponseType = &service.Response_AttachResponse{
		AttachResponse: &service.AttachResponse{
			Run: h.runRecord,
		},
	}
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

func (h *Handler) handleRun(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleConfig(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleAlert(record *service.Record) {
	h.sendRecord(record)
}

func (h *Handler) handleExit(record *service.Record) {
	h.sendRecord(record)
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

func (h *Handler) flushHistory(history *service.HistoryRecord) {

	if history == nil || history.Item == nil {
		return
	}
	// walk through items looking for _timestamp
	// TODO: add a timestamp field to the history record
	items := history.GetItem()
	var runTime float64 = 0
	for _, item := range items {
		if item.Key == "_timestamp" {
			val, err := strconv.ParseFloat(item.ValueJson, 64)
			if err != nil {
				h.logger.CaptureError("error parsing timestamp", err)
			} else {
				runTime = val - h.startTime
			}
		}
	}

	history.Item = append(history.Item,
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
		&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", history.GetStep().GetNum())},
	)

	record := &service.Record{
		RecordType: &service.Record_History{History: history},
	}
	summaryRecord := nexuslib.ConsolidateSummaryItems(h.consolidatedSummary, history.Item)
	h.sendRecord(summaryRecord)
	h.sendRecord(record)
}

func (h *Handler) handlePartialHistory(_ *service.Record, request *service.PartialHistoryRequest) {

	// This is the first partial history record we receive
	// for this step, so we need to initialize the history record
	// and step. If the user provided a step in the request,
	// use that, otherwise use 0.
	if h.historyRecord == nil {
		h.historyRecord = &service.HistoryRecord{}
		if request.Step != nil {
			h.historyRecord.Step = request.Step
		} else {
			h.historyRecord.Step = &service.HistoryStep{Num: h.runRecord.StartingStep}
		}
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
	// - If the request has a flush flag, another flush might occur after for the
	// current history record after processing the request.
	//
	// - If the request doesn't have a step, and doesn't have a flush flag, this is
	//	equivalent to step being equal to the current step number and a flush flag
	//	being set to true.
	if request.Step != nil {
		if request.Step.Num > h.historyRecord.Step.Num {
			h.flushHistory(h.historyRecord)
			h.historyRecord = &service.HistoryRecord{
				Step: request.Step,
			}
		} else if request.Step.Num < h.historyRecord.Step.Num {
			// h.logger.CaptureWarn("received history record for a step that has already been received",
			//	"received", request.Step, "current", h.historyRecord.Step)
			return
		}
	}

	// Append the history items from the request to the current history record.
	h.historyRecord.Item = append(h.historyRecord.Item, request.Item...)

	// Flush the history record and start to collect a new one with
	// the next step number.
	if (request.Step == nil && request.Action == nil) || request.Action.Flush {
		h.flushHistory(h.historyRecord)
		h.historyRecord = &service.HistoryRecord{
			Step: &service.HistoryStep{
				Num: h.historyRecord.Step.Num + 1,
			},
		}
	}
}

func (h *Handler) handleSummary(record *service.Record, summary *service.SummaryRecord) {
	summaryRecord := nexuslib.ConsolidateSummaryItems(h.consolidatedSummary, summary.Update)
	h.sendRecord(summaryRecord)
}

func (h *Handler) GetRun() *service.RunRecord {
	return h.runRecord
}
