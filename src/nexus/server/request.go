package server

import (
    // "flag"
    "context"
    "fmt"
    // "io"
    "bufio"
    "encoding/binary"
    "google.golang.org/protobuf/proto"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "github.com/wandb/wandb/nexus/service"
)

// import "wandb.ai/wandb/wbserver/wandb_internal":

func respondServerResponse(stream Stream, msg *service.ServerResponse) {
    // fmt.Println("respond")
    out, err := proto.Marshal(msg)
    check(err)
    // fmt.Println("respond", len(out), out)

    writer := bufio.NewWriter(stream.conn)

    header := Header{Magic: byte('W')}
    header.DataLength = uint32(len(out))

    err = binary.Write(writer, binary.LittleEndian, &header)
    check(err)

    _, err = writer.Write(out)
    check(err)

    err = writer.Flush()
    check(err)
}

func handleInformInit(stream *Stream, msg *service.ServerInformInitRequest) {
    fmt.Println("PROCESS: INIT")
}

func handleInformStart(stream *Stream, msg *service.ServerInformStartRequest) {
    fmt.Println("PROCESS: START")
}

func handleInformFinish(stream *Stream, msg *service.ServerInformFinishRequest) {
    fmt.Println("PROCESS: FIN")
}

func handleCommunicate(stream *Stream, msg *service.Record) {
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
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
    stream.respond <-*resp
}

func handleRunExit(stream *Stream, rec *service.Record, runExit *service.RunExitRecord) {
    // TODO: need to flush stuff before responding with exit
    runExitResult := &service.RunExitResult{}
    result := &service.Result{
        ResultType: &service.Result_ExitResult{runExitResult},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
    stream.respond <-*resp
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
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
    stream.respond <-*resp
}

func handlePublish(stream *Stream, msg *service.Record) {
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

func handleInformTeardown(stream *Stream, msg *service.ServerInformTeardownRequest) {
    fmt.Println("PROCESS: TEARDOWN")
    stream.done <-true
    _, cancelCtx := context.WithCancel(stream.ctx)

    fmt.Println("PROCESS: TEARDOWN *****1")
    cancelCtx()
    fmt.Println("PROCESS: TEARDOWN *****2")
    // TODO: remove this?
    //os.Exit(1)

    stream.server.shutdown = true
    stream.server.listen.Close()
}

func handleLogWriter(stream Stream, msg service.Record) {
}

func handleServerRequest(stream *Stream, msg service.ServerRequest) {
    switch x := msg.ServerRequestType.(type) {
    case *service.ServerRequest_InformInit:
        handleInformInit(stream, x.InformInit)
    case *service.ServerRequest_InformStart:
        handleInformStart(stream, x.InformStart)
    case *service.ServerRequest_InformFinish:
        handleInformFinish(stream, x.InformFinish)
    case *service.ServerRequest_RecordPublish:
        handlePublish(stream, x.RecordPublish)
    case *service.ServerRequest_RecordCommunicate:
        handleCommunicate(stream, x.RecordCommunicate)
    case *service.ServerRequest_InformTeardown:
        handleInformTeardown(stream, x.InformTeardown)
    case nil:
        // The field is not set.
        panic("bad2")
    default:
        bad := fmt.Sprintf("UNKNOWN type %T", x)
        panic(bad)
    }
}
