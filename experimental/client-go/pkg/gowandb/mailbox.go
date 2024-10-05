package gowandb

import (
	"strings"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type MailboxHandle struct {
	responseChan chan *spb.Result
}

type Mailbox struct {
	handles map[string]*MailboxHandle
}

func NewMailbox() *Mailbox {
	mailbox := &Mailbox{}
	mailbox.handles = make(map[string]*MailboxHandle)
	return mailbox
}

func NewMailboxHandle() *MailboxHandle {
	mbh := &MailboxHandle{responseChan: make(chan *spb.Result)}
	return mbh
}

func (mbh *MailboxHandle) wait() *spb.Result {
	got := <-mbh.responseChan
	return got
}

func (mb *Mailbox) Deliver(rec *spb.Record) *MailboxHandle {
	uuid := "core:" + GenerateUniqueID(12)
	rec.Control = &spb.Control{MailboxSlot: uuid}
	handle := NewMailboxHandle()
	mb.handles[uuid] = handle
	return handle
}

func (mb *Mailbox) Respond(result *spb.Result) bool {
	slot := result.GetControl().MailboxSlot
	if !strings.HasPrefix(slot, "core:") {
		return false
	}
	handle, ok := mb.handles[slot]
	if ok {
		handle.responseChan <- result
		// clean up after thyself?
		delete(mb.handles, slot)
	}
	return ok
}
