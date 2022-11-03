package server

import (
    // "flag"
    "context"
    "fmt"
    // "io"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "github.com/wandb/wandb/nexus/service"
)

// import "wandb.ai/wandb/wbserver/wandb_internal":

type Stream struct {
    exit chan struct{}
    done chan bool
    // process chan service.ServerRequest
    respond chan service.Result
    // respond chan service.ServerResponse
    writer chan service.Record
    ctx context.Context
    server *NexusServer
    shutdown bool
}

func (ns *Stream) init() {
    ns.exit = make(chan struct{})
    ns.done = make(chan bool, 1)
    ns.ctx = context.Background()
    ns.respond = make(chan service.Result)
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
            fmt.Println("PROCESS: DONE")
            return
        }
    }
}

func handleInformInit(nc *NexusConn, msg *service.ServerInformInitRequest) {
    fmt.Println("PROCESS: INIT")

    // TODO make this a mapping
    fmt.Println("STREAM init")
    nc.mux = &Stream{}
    nc.mux.init()
    go nc.mux.responder(nc)
}

func handleInformStart(nc *NexusConn, msg *service.ServerInformStartRequest) {
    fmt.Println("PROCESS: START")
}

func handleInformFinish(nc *NexusConn, msg *service.ServerInformFinishRequest) {
    fmt.Println("PROCESS: FIN")
}


func getStream(nc *NexusConn) (*Stream) {
    return nc.mux
}

func handleCommunicate(nc *NexusConn, msg *service.Record) {
    stream := getStream(nc)

    ref := msg.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("record_type")).Number()
    fmt.Printf("PROCESS: COMMUNICATE %d\n", num)
    
    switch x := msg.RecordType.(type) {
    case *service.Record_Request:
        // fmt.Println("reqgot:", x)
        handleRequest(stream, msg, x.Request)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
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
    stream.respond <-*result
}

func handleRequest(stream *Stream, rec *service.Record, req *service.Request) {
    ref := req.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("request_type")).Number()
    fmt.Printf("PROCESS: REQUEST %d\n", num)

    response := &service.Response{}
    result := &service.Result{
        ResultType: &service.Result_Response{response},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    stream.respond <-*result
}

func handlePublish(nc *NexusConn, msg *service.Record) {
    stream := getStream(nc)

    ref := msg.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("record_type")).Number()
    fmt.Printf("PROCESS: PUBLISH %d\n", num)

    // stream.writer <-*msg

    switch x := msg.RecordType.(type) {
    case *service.Record_Header:
        // fmt.Println("headgot:", x)
    case *service.Record_Request:
        fmt.Println("reqgot:", x)
        handleRequest(stream, msg, x.Request)
    case *service.Record_Summary:
        // fmt.Println("sumgot:", x)
    case *service.Record_Run:
        // fmt.Println("rungot:", x)
        handleRun(stream, msg, x.Run)
    case *service.Record_History:
        // fmt.Println("histgot:", x)
    case *service.Record_Telemetry:
        // fmt.Println("telgot:", x)
    case *service.Record_OutputRaw:
        // fmt.Println("outgot:", x)
    case *service.Record_Exit:
        // fmt.Println("exitgot:", x)
        handleRunExit(stream, msg, x.Exit)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
}

func handleInformTeardown(nc *NexusConn, msg *service.ServerInformTeardownRequest) {
    fmt.Println("PROCESS: TEARDOWN")
    nc.done <-true
    _, cancelCtx := context.WithCancel(nc.ctx)

    fmt.Println("PROCESS: TEARDOWN *****1")
    cancelCtx()
    fmt.Println("PROCESS: TEARDOWN *****2")
    // TODO: remove this?
    //os.Exit(1)

    nc.server.shutdown = true
    nc.server.listen.Close()
}

func handleLogWriter(stream Stream, msg service.Record) {
}

func handleServerRequest(nc *NexusConn, msg service.ServerRequest) {
    switch x := msg.ServerRequestType.(type) {
    case *service.ServerRequest_InformInit:
        handleInformInit(nc, x.InformInit)
    case *service.ServerRequest_InformStart:
        handleInformStart(nc, x.InformStart)
    case *service.ServerRequest_InformFinish:
        handleInformFinish(nc, x.InformFinish)
    case *service.ServerRequest_RecordPublish:
        handlePublish(nc, x.RecordPublish)
    case *service.ServerRequest_RecordCommunicate:
        handleCommunicate(nc, x.RecordCommunicate)
    case *service.ServerRequest_InformTeardown:
        handleInformTeardown(nc, x.InformTeardown)
    case nil:
        // The field is not set.
        panic("bad2")
    default:
        bad := fmt.Sprintf("UNKNOWN type %T", x)
        panic(bad)
    }
}
