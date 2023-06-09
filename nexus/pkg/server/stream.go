package server

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type Stream struct {
	handler   *Handler
	responder *Responder
	mailbox   *Mailbox
	settings  *Settings
	finished  bool
}

func NewStream(respondServerResponse func(context.Context, *service.ServerResponse),
	settings *Settings) *Stream {

	mailbox := NewMailbox()
	responder := NewResponder(respondServerResponse, mailbox)
	handler := NewHandler(responder.RespondResult, settings)
	return &Stream{responder: responder, handler: handler, mailbox: mailbox, settings: settings}
}

func (ns *Stream) Deliver(rec *service.Record) *MailboxHandle {
	handle := ns.mailbox.Deliver(rec)
	ns.ProcessRecord(rec)
	return handle
}

func (ns *Stream) ProcessRecord(rec *service.Record) {
	ns.handler.HandleRecord(rec)
}

func (ns *Stream) MarkFinished() {
	ns.finished = true
}

func (ns *Stream) IsFinished() bool {
	return ns.finished
}

func (ns *Stream) GetSettings() *Settings {
	return ns.settings
}

func (ns *Stream) GetRun() *service.RunRecord {
	return ns.handler.GetRun()
}
