package server

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type Stream struct {
	handler   *Handler
	responder *Responder
}

func NewStream(respondServerResponse func(context.Context, *service.ServerResponse),
	settings *Settings) *Stream {
	responder := NewResponder(respondServerResponse)
	handler := NewHandler(responder.RespondResult, settings)
	return &Stream{responder: responder, handler: handler}
}

func (ns *Stream) ProcessRecord(rec *service.Record) {
	ns.handler.HandleRecord(rec)
}
