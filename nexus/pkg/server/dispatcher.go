package server

import (
	"context"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
)

// Dispatcher is the dispatcher for a stream
type Dispatcher struct {
	// ctx is the context for the dispatcher
	ctx context.Context

	// inChan is the channel for incoming messages
	inChan chan *service.Result

	// responders is the map of responders
	responders map[string]Responder

	// logger is the logger for the dispatcher
	logger *slog.Logger
}

// NewDispatcher creates a new dispatcher
func NewDispatcher(ctx context.Context, logger *slog.Logger) *Dispatcher {
	dispatcher := &Dispatcher{
		ctx:        ctx,
		inChan:     make(chan *service.Result),
		responders: make(map[string]Responder),
		logger:     logger,
	}
	return dispatcher
}

// AddResponder adds a responder to the dispatcher
func (d *Dispatcher) AddResponder(entry ResponderEntry) {
	responderId := entry.ID
	if _, ok := d.responders[responderId]; !ok {
		d.responders[responderId] = entry.Responder
	} else {
		d.logger.Warn("Responder already exists", "responder", responderId)
	}
}

// RemoveResponder removes a responder from the dispatcher
//func (d *Dispatcher) RemoveResponder(responderId string) {
//	if _, ok := d.responders[responderId]; ok {
//		delete(d.responders, responderId)
//	} else {
//		slog.LogAttrs(
//			d.ctx,
//			slog.LevelError,
//			"Responder does not exist",
//			slog.String("responder", responderId))
//	}
//}

// do start the dispatcher and dispatches messages
func (d *Dispatcher) do() {

	d.logger.Info("dispatch: started")

	for msg := range d.inChan {
		responderId := msg.GetControl().GetConnectionId()
		d.logger.Debug("dispatch: got msg", "msg", msg)
		response := &service.ServerResponse{
			ServerResponseType: &service.ServerResponse_ResultCommunicate{ResultCommunicate: msg},
		}
		if responderId == "" {
			LogResult(slog.Default(), "dispatch: got msg with no connection id", msg)
			continue
		}
		d.responders[responderId].Respond(response)
	}

	d.logger.Info("dispatch: finished")
}
