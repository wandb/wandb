package server

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"

	// "time"

	log "github.com/sirupsen/logrus"
)

type Handler struct {
	handlerChan chan *service.Record

	currentStep int64
	startTime   float64

	wg     *sync.WaitGroup
	writer *Writer
	sender *Sender
	run    service.RunRecord

	summary map[string]string

	settings      *Settings
	respondResult func(result *service.Result)
}

func NewHandler(respondResult func(result *service.Result), settings *Settings) *Handler {
	var writer *Writer
	wg := sync.WaitGroup{}
	if settings.NoWrite == false {
		writer = NewWriter(&wg, settings)
	}
	sender := NewSender(&wg, respondResult, settings)
	handler := Handler{
		wg:            &wg,
		writer:        writer,
		sender:        sender,
		respondResult: respondResult,
		settings:      settings,
		summary:       make(map[string]string),
		handlerChan:   make(chan *service.Record)}
	sender.SetHandler(&handler)

	go handler.handlerGo()
	return &handler
}

func (handler *Handler) Stop() {
	close(handler.handlerChan)
}

func (handler *Handler) HandleRecord(rec *service.Record) {
	handler.handlerChan <- rec
}

func (h *Handler) shutdownStream() {
	log.Debug("HANDLER: shutdown")
	if h.writer != nil {
		h.writer.Stop()
	}
	// DONE ALREADY in defer path
	// h.sender.Stop()
	log.Debug("HANDLER: shutdown wait")
	h.wg.Wait()
	log.Debug("HANDLER: shutdown done")
}

func (h *Handler) captureRunInfo(run *service.RunRecord) {
	h.startTime = float64(run.StartTime.AsTime().UnixMicro()) / 1e6
	h.run = *run
}

func (h *Handler) handleRunStart(rec *service.Record, req *service.RunStartRequest) {
	h.captureRunInfo(req.Run)
	h.sender.SendRecord(rec)
}

func (h *Handler) handleRun(rec *service.Record, run *service.RunRecord) {
	// runResult := &service.RunUpdateResult{Run: run}

	// let sender take care of it
	h.sender.SendRecord(rec)

	/*
	   result := &service.Result{
	       ResultType: &service.Result_RunResult{runResult},
	       Control: rec.Control,
	       Uuid: rec.Uuid,
	   }
	   stream.respond <-*result
	*/
}

func (h *Handler) handleRunExit(rec *service.Record, runExit *service.RunExitRecord) {
	control := rec.GetControl()
	if control != nil {
		control.AlwaysSend = true
	}
	h.sender.SendRecord(rec)

	// TODO: need to flush stuff before responding with exit
	// runExitResult := &service.RunExitResult{}
	// result := &service.Result{
	// 	ResultType: &service.Result_ExitResult{runExitResult},
	// 	Control:    rec.Control,
	// 	Uuid:       rec.Uuid,
	// }
	// h.respondResult(result)
	// FIXME: hack to make sure that filestream has no data before continuing
	// time.Sleep(2 * time.Second)
	// h.shutdownStream()
}

func (h *Handler) handleGetSummary(rec *service.Record, msg *service.GetSummaryRequest, resp *service.Response) {
	items := []*service.SummaryItem{}

	for key, element := range h.summary {
		items = append(items, &service.SummaryItem{Key: key, ValueJson: element})
	}

	r := service.GetSummaryResponse{Item: items}
	resp.ResponseType = &service.Response_GetSummaryResponse{GetSummaryResponse: &r}
}

func (h *Handler) handleDefer(rec *service.Record, msg *service.DeferRequest) {
	h.sender.SendRecord(rec)
	h.shutdownStream()
}

func (h *Handler) updateSummary(msg *service.HistoryRecord) {
	items := msg.Item
	for i := 0; i < len(items); i++ {
		h.summary[items[i].Key] = items[i].ValueJson
	}
}

func (h *Handler) handleRequest(rec *service.Record, req *service.Request) {
	ref := req.ProtoReflect()
	desc := ref.Descriptor()
	num := ref.WhichOneof(desc.Oneofs().ByName("request_type")).Number()
	log.WithFields(log.Fields{"type": num}).Debug("PROCESS: REQUEST")
	noResult := false

	response := &service.Response{}

	switch x := req.RequestType.(type) {
	case *service.Request_PartialHistory:
		log.WithFields(log.Fields{"req": x}).Debug("PROCESS: got partial")
		h.handlePartialHistory(rec, x.PartialHistory)
		noResult = true
	case *service.Request_RunStart:
		log.WithFields(log.Fields{"req": x}).Debug("PROCESS: got start")
		h.handleRunStart(rec, x.RunStart)
	case *service.Request_GetSummary:
		h.handleGetSummary(rec, x.GetSummary, response)
	case *service.Request_Defer:
		h.handleDefer(rec, x.Defer)
	case *service.Request_CheckVersion:
	case *service.Request_StopStatus:
	case *service.Request_NetworkStatus:
	case *service.Request_PollExit:
	case *service.Request_ServerInfo:
	case *service.Request_SampledHistory:
	case *service.Request_Shutdown:
	case *service.Request_Keepalive:
	default:
		bad := fmt.Sprintf("REC UNKNOWN Request type %T", x)
		panic(bad)
	}

	if noResult {
		return
	}

	result := &service.Result{
		ResultType: &service.Result_Response{response},
		Control:    rec.Control,
		Uuid:       rec.Uuid,
	}
	h.respondResult(result)
}

func (handler *Handler) handleRecord(msg *service.Record) {
	// fmt.Println("HANDLEREC", msg)
	switch x := msg.RecordType.(type) {
	case *service.Record_Header:
		// fmt.Println("headgot:", x)
	case *service.Record_Request:
		log.WithFields(log.Fields{"req": x}).Debug("reqgot")
		handler.handleRequest(msg, x.Request)
	case *service.Record_Summary:
		// fmt.Println("sumgot:", x)
	case *service.Record_Run:
		// fmt.Println("rungot:", x)
		handler.handleRun(msg, x.Run)
	case *service.Record_Files:
		handler.sender.SendRecord(msg)
	case *service.Record_History:
		// fmt.Println("histgot:", x)
	case *service.Record_Telemetry:
		// fmt.Println("telgot:", x)
	case *service.Record_OutputRaw:
		// fmt.Println("outgot:", x)
	case *service.Record_Exit:
		// fmt.Println("exitgot:", x)
		handler.handleRunExit(msg, x.Exit)
	case nil:
		// The field is not set.
		panic("bad2rec")
	default:
		bad := fmt.Sprintf("REC UNKNOWN type %T", x)
		panic(bad)
	}
}

func (h *Handler) storeRecord(msg *service.Record) {
	switch msg.RecordType.(type) {
	case *service.Record_Request:
		// dont log this
	case nil:
		// The field is not set.
		panic("bad3rec")
	default:
		if h.writer != nil {
			h.writer.WriteRecord(msg)
		}
	}
}

func (handler *Handler) handlerGo() {
	log.Debug("HANDLER")
	for {
		select {
		case record := <-handler.handlerChan:
			log.WithFields(log.Fields{"rec": record}).Debug("HANDLER")
			handler.storeRecord(record)
			handler.handleRecord(record)
		}
	}
	log.Debug("HANDLER OUT")
}
