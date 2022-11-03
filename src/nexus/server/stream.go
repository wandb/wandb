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

/*
func handleLogWriter(stream Stream, msg service.Record) {
}
*/
