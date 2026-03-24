package runhandle

import (
	"errors"
	"sync"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/runupserter"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHandle contains objects that are initialized after the first RunRecord.
//
// Code that calls the getter methods implicitly relies on only running after
// the first RunRecord is received and processed.
type RunHandle struct {
	mu sync.Mutex

	// ready is closed when Init is called for the first time.
	ready chan struct{}

	// upserter tracks and syncs some of the stream's run's metadata.
	//
	// It is nil before the run is initialized.
	upserter *runupserter.RunUpserter

	// unsentTelemetry is telemetry that was recorded before the run
	// was initialized.
	unsentTelemetry *spb.TelemetryRecord
}

func New() *RunHandle {
	return &RunHandle{ready: make(chan struct{})}
}

// Ready returns a channel that's closed after Init is called the first time.
func (h *RunHandle) Ready() <-chan struct{} {
	return h.ready
}

// UpdateTelemetry records updates to the run's telemetry.
//
// If the run is not yet initialized, the telemetry change is stored and
// applied once the run becomes initialized.
func (h *RunHandle) UpdateTelemetry(telemetry *spb.TelemetryRecord) {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.upserter != nil {
		h.upserter.UpdateTelemetry(telemetry)
		return
	}

	// If the run hasn't been initialized, buffer the telemetry to send
	// it later.
	if h.unsentTelemetry == nil {
		h.unsentTelemetry = &spb.TelemetryRecord{}
	}

	proto.Merge(h.unsentTelemetry, telemetry)
}

// Init sets the run upserter.
//
// It is an error to call this more than once.
func (h *RunHandle) Init(upserter *runupserter.RunUpserter) error {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.upserter != nil {
		return errors.New("runhandle: run is already set")
	}
	if upserter == nil {
		return errors.New("runhandle: nil upserter")
	}

	h.upserter = upserter
	close(h.ready)

	if h.unsentTelemetry != nil {
		upserter.UpdateTelemetry(h.unsentTelemetry)
		h.unsentTelemetry = nil // Release memory.
	}

	return nil
}

// Upserter returns the run upserter if it has been initialized.
//
// Returns an error if no run upserter has been set.
func (h *RunHandle) Upserter() (*runupserter.RunUpserter, error) {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.upserter == nil {
		return nil, errors.New("runhandle: run not yet initialized")
	}

	return h.upserter, nil
}
