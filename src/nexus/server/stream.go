package server

import (
    "github.com/wandb/wandb/nexus/service"
)

type Stream struct {
    handler *Handler
    responder *Responder
}

func NewStream(respondServerResponse func(*service.ServerResponse)) (*Stream) {
    responder := NewResponder(respondServerResponse)
    handler := NewHandler(responder.RespondResult)
    return &Stream{responder: responder, handler: handler}
}

func (ns *Stream) ProcessRecord(rec *service.Record) {
    ns.handler.HandleRecord(rec)
}
