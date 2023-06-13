package server

import (
	"context"
	"sync"

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

func showFooter(result *service.Result, run *service.RunRecord, settings *Settings) {
	// todo: move this elsewhere more appropriate
	PrintHeadFoot(run, settings)
}

func (ns *Stream) Close(wg *sync.WaitGroup) {
	defer wg.Done()

	if ns.IsFinished() {
		return
	}
	exitRecord := service.RunExitRecord{}
	record := service.Record{
		RecordType: &service.Record_Exit{Exit: &exitRecord},
	}
	handle := ns.Deliver(&record)
	got := handle.wait()
	settings := ns.GetSettings()
	run := ns.GetRun()
	showFooter(got, run, settings)
	ns.MarkFinished()
}
