package handler_test

import (
	"context"

	"github.com/wandb/wandb/core/internal/observability"
	handler "github.com/wandb/wandb/core/internal/server/stream/handler"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func makeInboundChannels() (chan *pb.Record, chan *pb.Record) {
	inChan := make(chan *pb.Record, 1)
	loopbackChan := make(chan *pb.Record, 1)
	return inChan, loopbackChan
}

func makeOutboundChannels() (chan *pb.Record, chan *pb.Result) {
	fwdChan := make(chan *pb.Record, 1)
	outChan := make(chan *pb.Result, 1)
	return fwdChan, outChan
}

func makeHandler(
	inChan, loopbackChan, fwdChan chan *pb.Record,
	outChan chan *pb.Result,
	debounce bool,
) *handler.Handler {
	h := handler.NewHandler(context.Background(),
		observability.NewNoOpLogger(),
		handler.WithHandlerSettings(&pb.Settings{}),
		handler.WithHandlerFwdChannel(fwdChan),
		handler.WithHandlerOutChannel(outChan),
	)

	go h.Do(inChan)

	return h
}
