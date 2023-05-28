package server

import (
	// "context"
	"github.com/wandb/wandb/nexus/pkg/service"
	// "github.com/Khan/genqlient/graphql"
	//    log "github.com/sirupsen/logrus"
)

type Responder struct {
	responderChan chan *service.Result
}

func NewResponder(respondServerResponse func(result *service.ServerResponse)) *Responder {
	responder := Responder{}
	responder.responderChan = make(chan *service.Result)
	go responder.responderGo(respondServerResponse)
	return &responder
}

func (resp *Responder) RespondResult(rec *service.Result) {
	resp.responderChan <- rec
}

func (resp *Responder) responderGo(respondServerResponse func(result *service.ServerResponse)) {
	for result := range resp.responderChan {
		// fmt.Println("GOT", result)
		// respondServerResponse(nc, &msg)
		resp := &service.ServerResponse{
			ServerResponseType: &service.ServerResponse_ResultCommunicate{ResultCommunicate: result},
		}
		respondServerResponse(resp)
		/*
		   case <-ns.done:
		       log.Debug("PROCESS: DONE")
		       return
		*/
	}
}
