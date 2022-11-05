package server

import (
    "context"
    "fmt"
    "sync"
    "github.com/wandb/wandb/nexus/service"
    log "github.com/sirupsen/logrus"
)


type Stream struct {
    exit chan struct{}
    done chan bool
    // process chan service.ServerRequest
    respond chan service.Result
    // respond chan service.ServerResponse
    handlerChan chan service.Record
    writerChan chan service.Record
    ctx context.Context
    server *NexusServer
    shutdown bool
    wg sync.WaitGroup
    currentStep int64
    startTime float64
}

func (ns *Stream) init() {
    ns.exit = make(chan struct{})
    ns.done = make(chan bool, 1)
    ns.ctx = context.Background()
    ns.respond = make(chan service.Result)
    ns.handlerChan = make(chan service.Record)
    ns.writerChan = make(chan service.Record)

    go ns.handler()
    go ns.writer()
}

func (ns *Stream) responder(nc *NexusConn) {
    for {
        select {
        case result := <-ns.respond:
            // fmt.Println("GOT", result)
            //respondServerResponse(nc, &msg)
            resp := &service.ServerResponse{
                ServerResponseType: &service.ServerResponse_ResultCommunicate{&result},
            }
            nc.respondChan <-*resp
        case <-ns.done:
            log.Debug("PROCESS: DONE")
            return
        }
    }
}

func (ns *Stream) shutdownWriter() {
    close(ns.writerChan)
    ns.wg.Wait()
}

func handleRun(stream *Stream, rec *service.Record, run *service.RunRecord) {
    runResult := &service.RunUpdateResult{Run: run}
    result := &service.Result{
        ResultType: &service.Result_RunResult{runResult},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    stream.respond <-*result
}

func handleRunExit(stream *Stream, rec *service.Record, runExit *service.RunExitRecord) {
    // TODO: need to flush stuff before responding with exit
    runExitResult := &service.RunExitResult{}
    result := &service.Result{
        ResultType: &service.Result_ExitResult{runExitResult},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    stream.shutdownWriter()
    stream.respond <-*result
}

func handleRequest(stream *Stream, rec *service.Record, req *service.Request) {
    ref := req.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("request_type")).Number()
    log.WithFields(log.Fields{"type": num}).Debug("PROCESS: REQUEST")

    switch x := req.RequestType.(type) {
    case *service.Request_PartialHistory:
        log.WithFields(log.Fields{"req": x}).Debug("PROCESS: got partial")
        stream.handlePartialHistory(rec, x.PartialHistory)
    case *service.Request_RunStart:
        log.WithFields(log.Fields{"req": x}).Debug("PROCESS: got start")
        stream.handleRunStart(rec, x.RunStart)
    default:
    }

    response := &service.Response{}
    result := &service.Result{
        ResultType: &service.Result_Response{response},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    stream.respond <-*result
}

func (ns *Stream) storeRecord(msg *service.Record) {
    switch msg.RecordType.(type) {
    case *service.Record_Request:
        // dont log this
    case nil:
        // The field is not set.
        panic("bad3rec")
    default:
        ns.writerChan <-*msg
    }
}

func (ns *Stream) handleRecord(msg *service.Record) {
    switch x := msg.RecordType.(type) {
    case *service.Record_Header:
        // fmt.Println("headgot:", x)
    case *service.Record_Request:
        log.WithFields(log.Fields{"req": x}).Debug("reqgot")
        handleRequest(ns, msg, x.Request)
    case *service.Record_Summary:
        // fmt.Println("sumgot:", x)
    case *service.Record_Run:
        // fmt.Println("rungot:", x)
        handleRun(ns, msg, x.Run)
    case *service.Record_History:
        // fmt.Println("histgot:", x)
    case *service.Record_Telemetry:
        // fmt.Println("telgot:", x)
    case *service.Record_OutputRaw:
        // fmt.Println("outgot:", x)
    case *service.Record_Exit:
        // fmt.Println("exitgot:", x)
        handleRunExit(ns, msg, x.Exit)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
}

func (ns *Stream) handler() {
    log.Debug("HANDLER")
    for {
        select {
        case record := <-ns.handlerChan:
            log.WithFields(log.Fields{"rec": record}).Debug("HANDLER")
            ns.storeRecord(&record)
            ns.handleRecord(&record)
        case <-ns.done:
            log.Debug("PROCESS: DONE")
            close(ns.writerChan)
            return
        }
    }
    log.Debug("HANDLER OUT")
}
