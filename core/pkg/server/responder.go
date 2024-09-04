package server

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Responder interface {
	Respond(response *spb.ServerResponse)
}

type ResponderEntry struct {
	Responder Responder
	ID        string
}

type Dispatcher struct {
	sync.RWMutex
	responders map[string]Responder
	logger     *observability.CoreLogger
}

func NewDispatcher(logger *observability.CoreLogger) *Dispatcher {
	return &Dispatcher{
		RWMutex:    sync.RWMutex{},
		logger:     logger,
		responders: make(map[string]Responder),
	}
}

// AddResponders adds the given responders to the stream's dispatcher.
func (d *Dispatcher) AddResponders(entries ...ResponderEntry) {
	d.Lock()
	defer d.Unlock()

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

// handleRespond sends the given result to the appropriate responder.
func (d *Dispatcher) handleRespond(result *spb.Result) {
	d.logger.Debug("dispatch: got result", "result", result)

	responderID := result.GetControl().GetConnectionId()
	if responderID == "" {
		d.logger.Debug("dispatch: got result with no connection id", "result", result)
		return
	}

	d.RLock()
	responder, ok := d.responders[responderID]
	d.RUnlock()

	if ok {
		responder.Respond(&spb.ServerResponse{
			ServerResponseType: &spb.ServerResponse_ResultCommunicate{
				ResultCommunicate: result,
			},
		})
	} else {
		d.logger.CaptureError(
			fmt.Errorf("dispatch: no responder found: %s", responderID))
	}
}
