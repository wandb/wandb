package runsyncstate

import (
	"encoding/json"
	"fmt"

	"github.com/rogpeppe/go-internal/lockedfile"
)

// syncStateSuffix is appended to a .wandb file's path to get the path of
// its sync state file.
const syncStateSuffix = ".syncstate"

// syncState is a run's saved upload state.
//
// It is stored in a file alongside the `.wandb` file, and may be updated
// when run data is uploaded to the server, either during `wandb sync` or
// during an online run's automatic upload.
type syncState struct {
	// StartingStep is the initial step number for the run.
	//
	// For new runs this is zero.
	// For forked runs this is specified by the user when they create the run.
	// For resumed runs, this is determined during the first upload.
	StartingStep *int64 `json:"starting_step,omitempty"`
}

type Store interface {
	GetOrInitStartingStep(startingStep int64) (int64, error)
}

// SyncStateStore reads and updates the sync state file for a
// single run.
type fileStore struct {
	// path is the path to the sync state file.
	path string
}

type noopStore struct{}

func Noop() Store {
	return &noopStore{}
}

func (s *noopStore) GetOrInitStartingStep(startingStep int64) (int64, error) {
	return startingStep, nil
}

// File returns a store for a run's sync state file.
func File(wandbFilePath string) Store {
	return &fileStore{path: wandbFilePath + syncStateSuffix}
}

// GetOrInitStartingStep returns the starting step previously initialized, if any.
//
// Otherwise, it persists startingStep so that future calls (including from
// other processes) return the same value.
//
// The read-check-write is performed under an exclusive file lock so that
// concurrent syncs of the same file can't race.
func (s *fileStore) GetOrInitStartingStep(
	startingStep int64,
) (int64, error) {
	var state syncState

	err := lockedfile.Transform(s.path, func(data []byte) ([]byte, error) {
		if len(data) > 0 {
			if err := json.Unmarshal(data, &state); err != nil {
				return nil, fmt.Errorf("runsync: failed to parse sync state file: %v", err)
			}
			if state.StartingStep != nil {
				return data, nil
			}
		}

		state.StartingStep = &startingStep
		updated, err := json.Marshal(state)
		if err != nil {
			return nil, fmt.Errorf("runsync: failed to encode sync state file: %v", err)
		}
		return updated, nil
	})
	if err != nil {
		return 0, fmt.Errorf("runsync: failed to update sync state file: %v", err)
	}
	return *state.StartingStep, nil
}
