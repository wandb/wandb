package server

import (
	"context"
	"fmt"
	"strconv"

	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"

	// "time"

	log "github.com/sirupsen/logrus"
)

type Handler struct {
	settings *Settings
	inChan   chan *service.Record
	outChan  chan<- *service.Record

	dispatcherChan dispatchChannel

	currentStep int64
	startTime   float64
	run         *service.RunRecord
	summary     map[string]string
}

func NewHandler(ctx context.Context, settings *Settings) *Handler {
	handler := Handler{
		inChan:   make(chan *service.Record),
		settings: settings,
		summary:  make(map[string]string),
	}
	return &handler
}

func (h *Handler) start() {
	for msg := range h.inChan {
		log.WithFields(log.Fields{"rec": msg}).Debug("handle: got msg")
		h.handleRecord(msg)
	}
}

func (h *Handler) close() {
	close(h.outChan)
}

//gocyclo:ignore
func (h *Handler) handleRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_Alert:
		// TODO: handle alert
	case *service.Record_Artifact:
		// TODO: handle artifact
	case *service.Record_Config:
		// TODO: handle config
	case *service.Record_Exit:
		h.handleExit(msg, x.Exit)
	case *service.Record_Files:
		h.handleFiles(msg, x.Files)
	case *service.Record_Final:
		// TODO: handle final
	case *service.Record_Footer:
		// TODO: handle footer
	case *service.Record_Header:
		// TODO: handle header
	case *service.Record_History:
		// TODO: handle history
	case *service.Record_LinkArtifact:
		// TODO: handle linkartifact
	case *service.Record_Metric:
		// TODO: handle metric
	case *service.Record_Output:
		// TODO: handle output
	case *service.Record_OutputRaw:
		// TODO: handle outputraw
	case *service.Record_Preempting:
		// TODO: handle preempting
	case *service.Record_Request:
		log.WithFields(log.Fields{"req": x}).Debug("reqgot")
		h.handleRequest(msg)
	case *service.Record_Run:
		h.handleRun(msg, x.Run)
	case *service.Record_Stats:
		// TODO: handle stats
	case *service.Record_Summary:
		// TODO: handle summary
	case *service.Record_Tbrecord:
		// TODO: handle tbrecord
	case *service.Record_Telemetry:
		// TODO: handle telemetry
	case nil:
		log.Fatal("handleRecord: record type is nil")
	default:
		log.Fatalf("handleRecord: unknown record type %T", x)
	}
}

func (h *Handler) handleRequest(rec *service.Record) {
	req := rec.GetRequest()
	ref := req.ProtoReflect()
	desc := ref.Descriptor()
	num := ref.WhichOneof(desc.Oneofs().ByName("request_type")).Number()
	log.WithFields(log.Fields{"type": num}).Debug("PROCESS: REQUEST")

	response := &service.Response{}
	switch x := req.RequestType.(type) {
	case *service.Request_CheckVersion:
		// TODO: handle checkversion
	case *service.Request_Defer:
		h.handleDefer(rec)
	case *service.Request_GetSummary:
		h.handleGetSummary(rec, x.GetSummary, response)
	case *service.Request_Keepalive:
	case *service.Request_NetworkStatus:
	case *service.Request_PartialHistory:
		log.WithFields(log.Fields{"req": x}).Debug("PROCESS: got partial")
		h.handlePartialHistory(rec, x.PartialHistory)
		return
	case *service.Request_PollExit:
	case *service.Request_RunStart:
		log.WithFields(log.Fields{"req": x}).Debug("PROCESS: got start")
		h.handleRunStart(rec, x.RunStart)
	case *service.Request_SampledHistory:
	case *service.Request_ServerInfo:
	case *service.Request_Shutdown:
	case *service.Request_StopStatus:
	default:
		log.Fatalf("handleRequest: unknown request type %T", x)
	}

	result := &service.Result{
		ResultType: &service.Result_Response{Response: response},
		Control:    rec.Control,
		Uuid:       rec.Uuid,
	}
	h.dispatcherChan.Deliver(result)
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
		log.Fatal("handleRunStart: failed to clone run")
	}
	h.sendRecord(rec)
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

	response.ResponseType = &service.Response_GetSummaryResponse{GetSummaryResponse: &service.GetSummaryResponse{Item: items}}
}

func (h *Handler) handleDefer(rec *service.Record) {
	// TODO: add defer state machine
	req := rec.GetRequest().GetDefer()
	switch req.State {
	case service.DeferRequest_END:
		h.close()
	default:
		h.sendRecord(rec)
	}
}

func (h *Handler) handlePartialHistory(_ *service.Record, req *service.PartialHistoryRequest) {
	items := req.Item

	stepNum := h.currentStep
	h.currentStep += 1
	s := service.HistoryStep{Num: stepNum}

	var runTime float64 = 0
	// walk through items looking for _timestamp
	for i := 0; i < len(items); i++ {
		if items[i].Key == "_timestamp" {
			val, err := strconv.ParseFloat(items[i].ValueJson, 64)
			if err != nil {
				log.Errorf("Error parsing _timestamp: %s", err)
			}
			runTime = val - h.startTime
		}
	}
	items = append(items,
		&service.HistoryItem{Key: "_runtime", ValueJson: fmt.Sprintf("%f", runTime)},
		&service.HistoryItem{Key: "_step", ValueJson: fmt.Sprintf("%d", stepNum)},
	)

	record := service.HistoryRecord{Step: &s, Item: items}

	r := service.Record{
		RecordType: &service.Record_History{History: &record},
	}
	h.updateSummary(&record)

	// TODO: remove this once we have handleHistory
	h.sendRecord(&r)

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
