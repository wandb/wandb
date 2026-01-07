package runhandle

import (
	"errors"
	"sync"

	"github.com/wandb/wandb/core/internal/runupserter"
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
}

func New() *RunHandle {
	return &RunHandle{ready: make(chan struct{})}
}

// Ready returns a channel that's closed after Init is called the first time.
func (h *RunHandle) Ready() <-chan struct{} {
	return h.ready
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
