package server

import (
	"fmt"
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

func (s *Dispatcher) Do(hChan, sChan <-chan *service.Result) {
	ok1 := true
	ok2 := true
	var result *service.Result
	for ok1 && ok2 {
		select {
		case result, ok1 = <-hChan:
			fmt.Println("got result from handler", ok1)
			if ok1 {
				s.handleRespond(result)
			}
		case result, ok2 = <-sChan:
			fmt.Println("got result from sender", ok2)
			if ok2 {
				s.handleRespond(result)
			}
		}
	}
	fmt.Println("dispatch: done!!!!")
	s.logger.Debug("dispatch: finished")
}

// NewDispatcher creates a new dispatcher with the given logger.
func NewDispatcher(logger *observability.NexusLogger) *Dispatcher {
	return &Dispatcher{
		logger:     logger,
		responders: map[string]Responder{},
	}
}
