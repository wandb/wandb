package stream

import (
	"errors"
	"sync"

	"github.com/wandb/wandb/core/internal/runupserter"
)

// StreamRun is the stream's run state.
type StreamRun struct {
	mu sync.Mutex

	// upserter tracks and syncs some of the stream's run's metadata.
	//
	// It is nil before the run is initialized.
	upserter *runupserter.RunUpserter
}

func NewStreamRun() *StreamRun {
	return &StreamRun{}
}

// SetRunUpserter sets the stream's run upserter.
//
// It is an error to call this more than once.
func (sr *StreamRun) SetRunUpserter(upserter *runupserter.RunUpserter) error {
	sr.mu.Lock()
	defer sr.mu.Unlock()

	if sr.upserter != nil {
		return errors.New("stream: run is already set")
	}

	sr.upserter = upserter
	return nil
}

// GetRunUpserter returns the stream's run upserter.
//
// Returns an error if no run upserter has been set.
func (sr *StreamRun) GetRunUpserter() (*runupserter.RunUpserter, error) {
	sr.mu.Lock()
	defer sr.mu.Unlock()

	if sr.upserter == nil {
		return nil, errors.New("stream: no run")
	}

	return sr.upserter, nil
}
