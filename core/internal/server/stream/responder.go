package stream

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type Responder interface {
	Respond(response *pb.ServerResponse)
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

func (d *Dispatcher) handleRespond(result *pb.Result) {
	responderId := result.GetControl().GetConnectionId()
	d.logger.Debug("dispatch: got result", "result", result)
	if responderId == "" {
		d.logger.Debug("dispatch: got result with no connection id", "result", result)
		return
	}
	response := &pb.ServerResponse{
		ServerResponseType: &pb.ServerResponse_ResultCommunicate{
			ResultCommunicate: result,
		},
	}
	if responder, ok := d.responders[responderId]; ok {
		responder.Respond(response)
	} else {
		err := fmt.Errorf("dispatch: no responder found: %s", responderId)
		d.logger.CaptureFatalAndPanic("dispatch: no responder found", err)
	}
}

func NewDispatcher(logger *observability.CoreLogger) *Dispatcher {
	return &Dispatcher{
		logger:     logger,
		responders: make(map[string]Responder),
	}
}
