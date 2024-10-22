package runstream

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Responders map[string]stream.Responder

type Dispatcher struct {
	sync.RWMutex
	responders Responders
	logger     *observability.CoreLogger
}

func NewDispatcher(logger *observability.CoreLogger) *Dispatcher {
	return &Dispatcher{
		RWMutex:    sync.RWMutex{},
		logger:     logger,
		responders: make(Responders),
	}
}

// AddResponders adds the given responders to the stream's dispatcher.
func (d *Dispatcher) AddResponders(entries ...stream.Responder) {
	d.Lock()
	defer d.Unlock()

	if d.responders == nil {
		d.responders = make(map[string]stream.Responder)
	}

	for _, entry := range entries {
		responderId := entry.GetID()
		if _, ok := d.responders[responderId]; !ok {
			d.responders[responderId] = entry
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
