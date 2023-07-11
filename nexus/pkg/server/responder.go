package server

import "github.com/wandb/wandb/nexus/pkg/service"

type Responder interface {
	Respond(response *service.ServerResponse)
}

type ResponderEntry struct {
	Responder Responder
	ID        string
}
