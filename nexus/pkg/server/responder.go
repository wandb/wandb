package server

import (
	"fmt"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/publisher"
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
	// responders is the map of responders for the stream
	responders map[string]Responder

	// logger is the logger for the dispatcher
	logger *observability.NexusLogger
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

func (s *Dispatcher) Do(resCh publisher.Channel) {
	for result := range resCh.Read() {
		switch x := result.(type) {
		case *service.Result:
			s.logger.Debug("dispatch: got result", "result", x)
			s.handleRespond(x)
		default:
			err := fmt.Errorf("dispatch: got unknown type: %T", x)
			s.logger.CaptureError("dispatch: got unknown type", err)
		}
	}
	s.logger.Debug("dispatch: finished")
}

// NewDispatcher creates a new dispatcher with the given logger.
func NewDispatcher(logger *observability.NexusLogger) *Dispatcher {
	return &Dispatcher{
		logger:     logger,
		responders: map[string]Responder{},
	}
}
