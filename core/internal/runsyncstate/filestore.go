package runsyncstate

import (
	"encoding/json"
	"fmt"

	"github.com/rogpeppe/go-internal/lockedfile"
)

// syncState is the content of the run's sync state file.
type syncState struct {
	// StartingStep is the initial step number for the run.
	//
	// For new runs this is zero.
	// For forked runs this is specified by the user when they create the run.
	// For resumed runs, this is determined during the first upload.
	StartingStep *int64 `json:"starting_step,omitempty"`
}

// fileStore implements Store with a file and file-level locks.
type fileStore struct {
	// path is the path to the sync state file.
	path string
}

// GetOrInitStartingStep implements Store.GetOrInitStartingStep.
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
