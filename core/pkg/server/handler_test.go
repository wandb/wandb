package server_test

import (
	"context"

	"github.com/wandb/wandb/core/pkg/observability"
	server "github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
)

func makeInboundChannels() (chan *service.Record, chan *service.Record) {
	inChan := make(chan *service.Record, server.BufferSize)
	loopbackChan := make(chan *service.Record, server.BufferSize)
	return inChan, loopbackChan
}

func makeOutboundChannels() (chan *service.Record, chan *service.Result) {
	fwdChan := make(chan *service.Record, server.BufferSize)
	outChan := make(chan *service.Result, server.BufferSize)
	return fwdChan, outChan
}

func makeHandler(
	inChan, loopbackChan, fwdChan chan *service.Record,
	outChan chan *service.Result,
	debounce bool,
) *server.Handler {
	logger := observability.NewNoOpLogger()
	h := server.NewHandler(context.Background(), &service.Settings{}, logger)

	h.SetInboundChannels(inChan, loopbackChan)
	h.SetOutboundChannels(fwdChan, outChan)

	if !debounce {
		h.DisableSummaryDebouncer()
	}

	go h.Handle()

	return h
}
