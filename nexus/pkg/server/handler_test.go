package server

import (
	"context"
	"testing"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

func makeInboundChannels() (chan *service.Record, chan *service.Record, chan *service.Record) {
	inChan := make(chan *service.Record, BufferSize)
	senderLoopbackChan := make(chan *service.Record, BufferSize)
	streamLoopbackChan := make(chan *service.Record, BufferSize)
	return inChan, senderLoopbackChan, streamLoopbackChan
}

func makeHandler(
	inChan,
	senderLoopbackChan,
	streamLoopbackChan chan *service.Record,
	debounce bool,
) *Handler {
	logger := observability.NewNexusLogger(SetupDefaultLogger(), nil)
	h := NewHandler(context.Background(), &service.Settings{}, logger)

	h.SetInboundChannels(inChan, senderLoopbackChan, streamLoopbackChan)
	handlerFwdChan := make(chan *service.Record, BufferSize)
	handlerOutChan := make(chan *service.Result, BufferSize)
	h.SetOutboundChannels(handlerFwdChan, handlerOutChan)

	if !debounce {
		h.summaryDebouncer = nil
	}

	go h.Handle()

	return h
}

func TestHandleRun(t *testing.T) {
	inChan, senderLoopbackChan, streamLoopbackChan := makeInboundChannels()
	h := makeHandler(inChan, senderLoopbackChan, streamLoopbackChan, false)

	runRecord := &service.Record{
		RecordType: &service.Record_Run{
			Run: &service.RunRecord{
				Config:  &service.ConfigRecord{},
				Project: "testProject",
				Entity:  "testEntity",
			}},
		Control: &service.Control{
			MailboxSlot: "junk",
		},
	}
	// вхо-о-одит
	inChan <- runRecord
	// и-и-и вы-ы-ыходит
	<-h.fwdChan
	// замечательно выходит!
}
