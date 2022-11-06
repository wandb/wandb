package server

import (
    // "context"
    "sync"
    "github.com/wandb/wandb/nexus/service"
    // "github.com/Khan/genqlient/graphql"

//    log "github.com/sirupsen/logrus"
)


type Stream struct {
    wg sync.WaitGroup

    sender *Sender
    handler *Handler
    fstream *FileStream
    writer *Writer
    responder *Responder
}

func NewStream(nexusConn *NexusConn) (*Stream) {
    stream := Stream{}

    stream.responder = stream.NewResponder(nexusConn)
    respondResult := stream.responder.RespondResult

    stream.writer = stream.NewWriter()
    writeRecord := stream.writer.WriteRecord

    stream.sender = stream.NewSender(respondResult)
    sendRecord := stream.sender.SendRecord

    stream.handler = stream.NewHandler(writeRecord, sendRecord, respondResult)
    return &stream
}

func (ns *Stream) ProcessRecord(rec *service.Record) {
    ns.handler.HandleRecord(rec)
}

func (ns *Stream) shutdownStream() {
    if ns.writer != nil {
        ns.writer.Stop()
    }
    if ns.sender != nil {
        ns.sender.Stop()
    }
    if ns.fstream != nil {
        ns.fstream.Stop()
    } 
    ns.wg.Wait()
}
