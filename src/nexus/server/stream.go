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

func NewStream(respondServerResponse func(*service.ServerResponse)) (*Stream) {
    stream := Stream{}

    stream.responder = NewResponder(respondServerResponse)
    respondResult := stream.responder.RespondResult

    stream.writer = NewWriter(&stream.wg)
    writeRecord := stream.writer.WriteRecord

    stream.sender = NewSender(&stream.wg, respondResult)
    sendRecord := stream.sender.SendRecord

    stream.handler = NewHandler(&stream.wg, writeRecord, sendRecord, respondResult, stream.shutdownStream)
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
