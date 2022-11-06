package server

import (
    // "context"
    "github.com/wandb/wandb/nexus/service"
    // "github.com/Khan/genqlient/graphql"

//    log "github.com/sirupsen/logrus"
)


type Responder struct {
    // exit chan struct{}
    // done chan bool
    // process chan service.ServerRequest
    responderChan chan service.Result
    // respond chan service.ServerResponse
    // senderChan chan service.Record
    // ctx context.Context
    // server *NexusServer
    // shutdown bool
}

func (ns *Stream) NewResponder(nexusConn *NexusConn) (*Responder) {
    responder := Responder{}
    responder.responderChan = make(chan service.Result)
    go responder.responderGo(nexusConn)
    return &responder
}

func (resp *Responder) RespondResult(rec *service.Result) {
    resp.responderChan <-*rec
}

func (resp *Responder) responderGo(nc *NexusConn) {
    for {
        select {
        case result := <-resp.responderChan:
            // fmt.Println("GOT", result)
            //respondServerResponse(nc, &msg)
            resp := &service.ServerResponse{
                ServerResponseType: &service.ServerResponse_ResultCommunicate{&result},
            }
            nc.respondChan <-*resp
            /*
        case <-ns.done:
            log.Debug("PROCESS: DONE")
            return
            */
        }
    }
}
