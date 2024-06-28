package server

import (
	"fmt"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type Responder interface {
	Respond(response *service.ServerResponse)
}

type ResponderEntry struct {
	Responder Responder
	ID        string
}

type Dispatcher struct {
	responders map[string]Responder
	logger     *observability.CoreLogger
}

// AddResponders adds the given responders to the stream's dispatcher.
func (d *Dispatcher) AddResponders(entries ...ResponderEntry) {
	if d.responders == nil {
		d.responders = make(map[string]Responder)
	}
	for _, entry := range entries {
		responderId := entry.ID
		if _, ok := d.responders[responderId]; !ok {
			d.responders[responderId] = entry.Responder
		} else {
			d.logger.CaptureWarn("Responder already exists", "responder", responderId)
		}
	}
}

func (d *Dispatcher) handleRespond(result *service.Result) {
	responderId := result.GetControl().GetConnectionId()
	d.logger.Debug("dispatch: got result", "result", result)
	if responderId == "" {
		d.logger.Debug("dispatch: got result with no connection id", "result", result)
		return
	}
	response := &service.ServerResponse{
		ServerResponseType: &service.ServerResponse_ResultCommunicate{
			ResultCommunicate: result,
		},
	}
	if responder, ok := d.responders[responderId]; ok {
		responder.Respond(response)
	} else {
		d.logger.CaptureFatalAndPanic(
			fmt.Errorf("dispatch: no responder found: %s", responderId))
	}
}

func NewDispatcher(logger *observability.CoreLogger) *Dispatcher {
	return &Dispatcher{
		logger:     logger,
		responders: make(map[string]Responder),
	}
}
