package server

import (
    //"context"
    "fmt"
    "github.com/wandb/wandb/nexus/service"
)

// import "wandb.ai/wandb/wbserver/wandb_internal":

func handleInformInit(nc *NexusConn, msg *service.ServerInformInitRequest) {
    fmt.Println("PROCESS: INIT")

    // TODO make this a mapping
    fmt.Println("STREAM init")
    // streamId := "thing"
    streamId := msg.XInfo.StreamId
    nc.mux[streamId] = &Stream{}
    nc.mux[streamId].init()

    // read from mux and write to nc
    go nc.mux[streamId].responder(nc)
}

func handleInformStart(nc *NexusConn, msg *service.ServerInformStartRequest) {
    fmt.Println("PROCESS: START")
}

func handleInformFinish(nc *NexusConn, msg *service.ServerInformFinishRequest) {
    fmt.Println("PROCESS: FIN")
}


func getStream(nc *NexusConn, streamId string) (*Stream) {
    //streamId := "thing"
    return nc.mux[streamId]
}

func handleInformRecord(nc *NexusConn, msg *service.Record) {
    streamId := msg.XInfo.StreamId
    stream := getStream(nc, streamId)

    ref := msg.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("record_type")).Number()
    fmt.Printf("PROCESS: COMM/PUBLISH %d\n", num)

    stream.handlerChan <-*msg
    fmt.Printf("PROCESS: COMM/PUBLISH %d 2\n", num)
}

func handleInformTeardown(nc *NexusConn, msg *service.ServerInformTeardownRequest) {
    fmt.Println("PROCESS: TEARDOWN")
    nc.done <-true
    // _, cancelCtx := context.WithCancel(nc.ctx)

    fmt.Println("PROCESS: TEARDOWN *****1")
    //cancelCtx()
    fmt.Println("PROCESS: TEARDOWN *****2")
    // TODO: remove this?
    //os.Exit(1)

    nc.server.shutdown = true
    nc.server.listen.Close()
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
        handleInformRecord(nc, x.RecordPublish)
    case *service.ServerRequest_RecordCommunicate:
        handleInformRecord(nc, x.RecordCommunicate)
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
