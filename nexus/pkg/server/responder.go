package server

import (
	// "context"
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
	// "github.com/Khan/genqlient/graphql"
	//    log "github.com/sirupsen/logrus"
)

type Responder struct {
	responderChan chan *service.Result
}

func NewResponder(respondServerResponse func(ctx context.Context, result *service.ServerResponse)) *Responder {
	responder := Responder{}
	responder.responderChan = make(chan *service.Result)
	go responder.responderGo(respondServerResponse)
	return &responder
}

func (resp *Responder) RespondResult(rec *service.Result) {
	resp.responderChan <- rec
}

func (resp *Responder) responderGo(respondServerResponse func(ctx context.Context, result *service.ServerResponse)) {
	for result := range resp.responderChan {
		// fmt.Println("GOT", result)
		// respondServerResponse(nc, &msg)
		resp := &service.ServerResponse{
			ServerResponseType: &service.ServerResponse_ResultCommunicate{ResultCommunicate: result},
		}
		// fixme: this is a hack to get the context
		respondServerResponse(context.Background(), resp)
		/*
		   case <-ns.done:
		       log.Debug("PROCESS: DONE")
		       return
		*/
	}
}
