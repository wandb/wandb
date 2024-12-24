package stream

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
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
	mu         sync.RWMutex
	responders map[string]Responder
	logger     *observability.CoreLogger
	ch         chan *spb.Result
	done       chan struct{}
}

func NewDispatcher(logger *observability.CoreLogger) *Dispatcher {
	return &Dispatcher{
		mu:         sync.RWMutex{},
		logger:     logger,
		responders: make(map[string]Responder),
		ch:         make(chan *spb.Result, BufferSize),
		done:       make(chan struct{}),
	}
}

// RegisterResponder adds the given responders to the stream's dispatcher.
func (d *Dispatcher) RegisterResponder(entry ResponderEntry) {
	d.mu.Lock()
	defer d.mu.Unlock()

	responderId := entry.ID
	if _, ok := d.responders[responderId]; !ok {
		d.responders[responderId] = entry.Responder
	} else {
		d.logger.CaptureWarn("Responder already exists", "responder", responderId)
	}
}

func (d *Dispatcher) UnregisterResponder(id string) {
	d.mu.Lock()
	defer d.mu.Unlock()

	delete(d.responders, id)
}

func (d *Dispatcher) Do() {
	for result := range d.ch {
		d.handleRespond(result)
	}
	close(d.done)
}

func (d *Dispatcher) Close() {
	close(d.ch)
	<-d.done
}

// handleRespond sends the given result to the appropriate responder.
func (d *Dispatcher) handleRespond(result *spb.Result) {
	d.logger.Debug("dispatch: got result", "result", result)

	responderID := result.GetControl().GetConnectionId()
	if responderID == "" {
		d.logger.Debug("dispatch: got result with no connection id", "result", result)
		return
	}

	d.mu.RLock()
	responder, ok := d.responders[responderID]
	d.mu.RUnlock()

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

func (d *Dispatcher) Chan() chan<- *spb.Result {
	return d.ch
}
