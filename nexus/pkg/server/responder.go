package server

import (
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
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
	logger     *observability.NexusLogger
}

// Run is the main loop of the dispatcher to process incoming messages
func (d *Dispatcher) Run(hChan, sChan <-chan *service.Result) {
	defer d.logger.Reraise()
	for hChan != nil || sChan != nil {
		select {
		case result, ok := <-hChan:
			if !ok {
				hChan = nil
				continue
			}
			d.handleRespond(result)
		case result, ok := <-sChan:
			if !ok {
				sChan = nil
				continue
			}
			d.handleRespond(result)
		}
	}
	d.logger.Debug("dispatch: finished")
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
	d.responders[responderId].Respond(response)
}

func NewDispatcher(logger *observability.NexusLogger) *Dispatcher {
	return &Dispatcher{
		logger:     logger,
		responders: make(map[string]Responder),
	}
}
