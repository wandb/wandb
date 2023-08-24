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

// do is the main loop of the dispatcher to process incoming messages
func (s *Dispatcher) do(hChan, sChan <-chan *service.Result) {
	for hChan != nil || sChan != nil {
		select {
		case result, ok := <-hChan:
			if !ok {
				hChan = nil
				continue
			}
			s.handleRespond(result)
		case result, ok := <-sChan:
			if !ok {
				sChan = nil
				continue
			}
			s.handleRespond(result)
		}
	}
	s.logger.Debug("dispatch: finished")
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *Dispatcher) AddResponders(entries ...ResponderEntry) {
	if s.responders == nil {
		s.responders = make(map[string]Responder)
	}
	for _, entry := range entries {
		responderId := entry.ID
		if _, ok := s.responders[responderId]; !ok {
			s.responders[responderId] = entry.Responder
		} else {
			s.logger.CaptureWarn("Responder already exists", "responder", responderId)
		}
	}
}

func (s *Dispatcher) handleRespond(result *service.Result) {
	responderId := result.GetControl().GetConnectionId()
	s.logger.Debug("dispatch: got result", "result", result)
	if responderId == "" {
		s.logger.Debug("dispatch: got result with no connection id", "result", result)
		return
	}
	response := &service.ServerResponse{
		ServerResponseType: &service.ServerResponse_ResultCommunicate{
			ResultCommunicate: result,
		},
	}
	s.responders[responderId].Respond(response)
}

func NewDispatcher(logger *observability.NexusLogger) *Dispatcher {
	return &Dispatcher{
		logger:     logger,
		responders: make(map[string]Responder),
	}
}
