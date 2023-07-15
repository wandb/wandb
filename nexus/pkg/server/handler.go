package server

import (
	"context"
	"fmt"
	"strconv"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
	"google.golang.org/protobuf/proto"
	// "time"
)

// Handler is the handler for a stream
// it handles the incoming messages process them
// and passes them to the writer
type Handler struct {
	// ctx is the context for the handler
	ctx context.Context

	// inChan is the channel for incoming messages
	inChan chan *service.Record

	// outChan is the channel for outgoing messages
	outChan chan<- *service.Record

	// dispatcherChan is the channel for dispatcher messages
	dispatcherChan chan<- *service.Result

	// settings is the settings for the handler
	settings *service.Settings

	// logger is the logger for the handler
	logger *observability.NexusLogger

	// startTime is the start time
	startTime float64

	// run is the run record
	run *service.RunRecord

	// summary is the summary
	summary map[string]string

	// historyRecord is the history record used to track
	// current active history record for the run
	historyRecord *service.HistoryRecord
}

// NewHandler creates a new handler
func NewHandler(ctx context.Context, settings *service.Settings, logger *observability.NexusLogger) *Handler {
	h := &Handler{
		ctx:      ctx,
		inChan:   make(chan *service.Record),
		settings: settings,
		summary:  make(map[string]string),
		logger:   logger,
	}
	return h
}

// do this starts the handler
func (h *Handler) do() {
	defer observability.Reraise()

	h.logger.Info("handler: started")

	for msg := range h.inChan {
		h.handleRecord(msg)
	}
	h.close()
	slog.Debug("handler: started and closed")
}

// close this closes the handler
func (h *Handler) close() {
	close(h.outChan)
	slog.Info("handle: closed", "stream_id", h.settings.RunId)
}

//gocyclo:ignore
func (h *Handler) handleRecord(msg *service.Record) {
	h.logger.Debug("handle: got a message", "msg", msg, "stream_id", h.settings.RunId)
	switch x := msg.RecordType.(type) {
	case *service.Record_Alert:
		// TODO: handle this
	case *service.Record_Artifact:
		// TODO: handle this
	case *service.Record_Config:
		// TODO: handle this
	case *service.Record_Exit:
		h.handleExit(msg, x.Exit)
	case *service.Record_Files:
		h.handleFiles(msg, x.Files)
	case *service.Record_Final:
		// TODO: handle this
	case *service.Record_Footer:
		// TODO: handle this
	case *service.Record_Header:
		// TODO: handle this
	case *service.Record_History:
	case *service.Record_LinkArtifact:
		// TODO: handle this
	case *service.Record_Metric:
		// TODO: handle this
	case *service.Record_Output:
		// TODO: handle this
	case *service.Record_OutputRaw:
		// TODO: handle this
	case *service.Record_Preempting:
		// TODO: handle this
	case *service.Record_Request:
		h.handleRequest(msg)
	case *service.Record_Run:
		h.handleRun(msg, x.Run)
	case *service.Record_Stats:
		// TODO: handle this
	case *service.Record_Summary:
		// TODO: handle this
	case *service.Record_Tbrecord:
		// TODO: handle this
	case *service.Record_Telemetry:
		// TODO: handle this
	case nil:
		err := fmt.Errorf("handleRecord: record type is nil")
		h.logger.CaptureFatalAndPanic("error handling record", err)
	default:
		err := fmt.Errorf("handleRecord: unknown record type %T", x)
		h.logger.CaptureFatalAndPanic("error handling record", err)
	}
}

func (h *Handler) handleRequest(rec *service.Record) {
	req := rec.GetRequest()
	response := &service.Response{}
	switch x := req.RequestType.(type) {
	case *service.Request_CheckVersion:
		// TODO: handle this
	case *service.Request_Defer:
		h.handleDefer(rec)
	case *service.Request_GetSummary:
		h.handleGetSummary(rec, x.GetSummary, response)
	case *service.Request_Keepalive:
	case *service.Request_NetworkStatus:
	case *service.Request_PartialHistory:
		h.handlePartialHistory(rec, x.PartialHistory)
		return
	case *service.Request_PollExit:
	case *service.Request_RunStart:
		h.handleRunStart(rec, x.RunStart)
	case *service.Request_SampledHistory:
	case *service.Request_ServerInfo:
	case *service.Request_Shutdown:
	case *service.Request_StopStatus:
	case *service.Request_JobInfo:
	case *service.Request_Attach:
		h.handleAttach(rec, x.Attach, response)
	default:
		err := fmt.Errorf("handleRequest: unknown request type %T", x)
		h.logger.CaptureFatalAndPanic("error handling request", err)
	}

	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    rec.Control,
		Uuid:       rec.Uuid,
	}
	h.dispatcherChan <- result
}

func (h *Handler) sendRecord(rec *service.Record) {
	control := rec.GetControl()
	if control != nil {
		control.AlwaysSend = true
	}
	h.outChan <- rec
}

func (h *Handler) handleRunStart(rec *service.Record, req *service.RunStartRequest) {
	var ok bool
	run := req.Run

	h.startTime = float64(run.StartTime.AsTime().UnixMicro()) / 1e6
	h.run, ok = proto.Clone(run).(*service.RunRecord)
	if !ok {
		err := fmt.Errorf("handleRunStart: failed to clone run")
		h.logger.CaptureFatalAndPanic("error handling run start", err)
	}
	h.sendRecord(rec)

	// NOTE: once this request arrives in the sender,
	// the latter will start its filestream and uploader

	// TODO: this is a hack, we should not be sending metadata from here,
	//  it should arrive as a proper request from the client.
	//  attempting to do this before the run start request arrives in the sender
	//  will cause a segfault because the sender's uploader is not initialized yet.
	h.handleMetadata(rec, req)
}

func (h *Handler) handleAttach(_ *service.Record, _ *service.AttachRequest, resp *service.Response) {

	resp.ResponseType = &service.Response_AttachResponse{
		AttachResponse: &service.AttachResponse{
			Run: h.run,
		},
	}
}

func (h *Handler) handleMetadata(_ *service.Record, req *service.RunStartRequest) {
	run := req.Run
	// Sending metadata as a request for now, eventually this should be turned into
	// a record and stored in the transaction log
	meta := service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{RequestType: &service.Request_Metadata{
				Metadata: &service.MetadataRequest{
					Os:        h.settings.GetXOs().GetValue(),
					Python:    h.settings.GetXPython().GetValue(),
					Host:      h.settings.GetHost().GetValue(),
					Cuda:      h.settings.GetXCuda().GetValue(),
					Program:   h.settings.GetProgram().GetValue(),
					StartedAt: run.StartTime}}}}}

	h.sendRecord(&meta)
}

func (h *Handler) handleRun(rec *service.Record, _ *service.RunRecord) {
	h.sendRecord(rec)
}

func (h *Handler) handleExit(msg *service.Record, _ *service.RunExitRecord) {
	h.sendRecord(msg)
}

func (h *Handler) handleFiles(rec *service.Record, _ *service.FilesRecord) {
	h.sendRecord(rec)
}

func (h *Handler) handleGetSummary(_ *service.Record, _ *service.GetSummaryRequest, response *service.Response) {
	var items []*service.SummaryItem

	for key, element := range h.summary {
		items = append(items, &service.SummaryItem{Key: key, ValueJson: element})
	}
	response.ResponseType = &service.Response_GetSummaryResponse{
		GetSummaryResponse: &service.GetSummaryResponse{
			Item: items,
		},
	}
}

func (h *Handler) handleDefer(rec *service.Record) {
	req := rec.GetRequest().GetDefer()
	switch req.State {
	case service.DeferRequest_BEGIN:
	case service.DeferRequest_FLUSH_STATS:
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
		err := fmt.Errorf("handleDefer: unknown defer state %v", req.State)
		h.logger.CaptureError("unknown defer state", err)
	}
	h.sendRecord(rec)
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

	rec := &service.Record{
		RecordType: &service.Record_History{History: history},
	}
	h.updateSummary(history)
	h.sendRecord(rec)
}

func (h *Handler) handlePartialHistory(_ *service.Record, req *service.PartialHistoryRequest) {

	// This is the first partial history record we receive
	// for this step, so we need to initialize the history record
	// and step. If the user provided a step in the request,
	// use that, otherwise use 0.
	if h.historyRecord == nil {
		h.historyRecord = &service.HistoryRecord{}
		if req.Step != nil {
			h.historyRecord.Step = req.Step
		} else {
			h.historyRecord.Step = &service.HistoryStep{Num: 0}
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
	if req.Step != nil {
		if req.Step.Num > h.historyRecord.Step.Num {
			h.flushHistory(h.historyRecord)
			h.historyRecord = &service.HistoryRecord{
				Step: req.Step,
			}
		} else if req.Step.Num < h.historyRecord.Step.Num {
			h.logger.CaptureWarn("received history record for a step that has already been received",
				"received", req.Step, "current", h.historyRecord.Step)
			return
		}
	}

	// Append the history items from the request to the current history record.
	h.historyRecord.Item = append(h.historyRecord.Item, req.Item...)

	// Flush the history record and start to collect a new one with
	// the next step number.
	if (req.Step == nil && req.Action == nil) || req.Action.Flush {
		h.flushHistory(h.historyRecord)
		h.historyRecord = &service.HistoryRecord{
			Step: &service.HistoryStep{
				Num: h.historyRecord.Step.Num + 1,
			},
		}
	}
}

func (h *Handler) updateSummary(msg *service.HistoryRecord) {
	items := msg.Item
	for i := 0; i < len(items); i++ {
		h.summary[items[i].Key] = items[i].ValueJson
	}
}

func (h *Handler) GetRun() *service.RunRecord {
	return h.run
}
