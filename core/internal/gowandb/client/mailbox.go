package gowandb

import (
	"strings"

	"github.com/wandb/wandb/core/internal/lib/corelib"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type MailboxHandle struct {
	responseChan chan *pb.Result
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
	mbh := &MailboxHandle{responseChan: make(chan *pb.Result)}
	return mbh
}

func (mbh *MailboxHandle) wait() *pb.Result {
	got := <-mbh.responseChan
	return got
}

func (mb *Mailbox) Deliver(rec *pb.Record) *MailboxHandle {
	uuid := "core:" + corelib.ShortID(12)
	rec.Control = &pb.Control{MailboxSlot: uuid}
	handle := NewMailboxHandle()
	mb.handles[uuid] = handle
	return handle
}

func (mb *Mailbox) Respond(result *pb.Result) bool {
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
