package gowandb

import (
	// "fmt"
	"context"
	"crypto/rand"
	"fmt"
	"log/slog"
	"strings"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type MailboxHandle struct {
	responseChan chan *service.Result
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
	mbh := &MailboxHandle{responseChan: make(chan *service.Result)}
	return mbh
}

func (mbh *MailboxHandle) wait() *service.Result {
	// fmt.Println("read from chan")
	got := <-mbh.responseChan
	// fmt.Println("XXXX  read from chan, got", got)
	return got
}

func (mb *Mailbox) Deliver(rec *service.Record) *MailboxHandle {
	uuid := "nexus:" + ShortID(12)
	rec.Control = &service.Control{MailboxSlot: uuid}
	// rec.GetControl().MailboxSlot = uuid
	// fmt.Println("mailbox record", rec)
	handle := NewMailboxHandle()
	mb.handles[uuid] = handle
	return handle
}

func (mb *Mailbox) Respond(result *service.Result) bool {
	// fmt.Println("mailbox result", result)
	slot := result.GetControl().MailboxSlot
	if !strings.HasPrefix(slot, "nexus:") {
		return false
	}
	handle, ok := mb.handles[slot]
	if ok {
		handle.responseChan <- result
	}
	return ok
}

var chars = "abcdefghijklmnopqrstuvwxyz1234567890"

func ShortID(length int) string {

	charsLen := len(chars)
	b := make([]byte, length)
	_, err := rand.Read(b) // generates len(b) random bytes
	if err != nil {
		err = fmt.Errorf("rand error: %s", err.Error())
		slog.LogAttrs(context.Background(),
			slog.LevelError,
			"ShortID: error",
			slog.String("error", err.Error()))
		panic(err)
	}

	for i := 0; i < length; i++ {
		b[i] = chars[int(b[i])%charsLen]
	}
	return string(b)
}
