package stream

import (
	"errors"
	"sync"

	"github.com/wandb/wandb/core/internal/runmetadata"
)

// StreamRun is the stream's run state.
type StreamRun struct {
	mu sync.Mutex

	// metadata is the metadata for the stream's run.
	//
	// It is nil before the run is initialized.
	metadata *runmetadata.RunMetadata
}

func NewStreamRun() *StreamRun {
	return &StreamRun{}
}

// SetRun sets the stream's run.
//
// It is an error to call this more than once.
func (sr *StreamRun) SetRun(metadata *runmetadata.RunMetadata) error {
	sr.mu.Lock()
	defer sr.mu.Unlock()

	if sr.metadata != nil {
		return errors.New("stream: run is already set")
	}

	sr.metadata = metadata
	return nil
}

// Metadata returns the stream's run metadata.
//
// Returns an error if no run has been set.
func (sr *StreamRun) Metadata() (*runmetadata.RunMetadata, error) {
	sr.mu.Lock()
	defer sr.mu.Unlock()

	if sr.metadata == nil {
		return nil, errors.New("stream: no run")
	}

	return sr.metadata, nil
}
