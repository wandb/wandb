package runsyncstate

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/rogpeppe/go-internal/lockedfile"
)

// syncState is the content of the run's sync state file.
type syncState struct {
	// StartingStep is the encoded StartState.StartStep.
	StartingStep *int64 `json:"starting_step,omitempty"`

	// StartingRuntimeMs is the StartState.StartRuntime in milliseconds.
	StartingRuntimeMs *int64 `json:"starting_runtime,omitempty"`
}

// fileStore implements Store with a file and file-level locks.
type fileStore struct {
	// path is the path to the sync state file.
	path string
}

// GetOrInitStartState implements Store.GetOrInitStartState.
func (s *fileStore) GetOrInitStartState(
	initialState StartState,
) (result StartState, err error) {
	err = lockedfile.Transform(s.path, func(data []byte) ([]byte, error) {
		var fileContent syncState

		if len(data) > 0 {
			if err := json.Unmarshal(data, &fileContent); err != nil {
				return nil, fmt.Errorf(
					"runsync: failed to parse sync state file: %v",
					err,
				)
			}
		}

		if fileContent.StartingStep != nil {
			result.StartStep = *fileContent.StartingStep
		} else {
			result.StartStep = initialState.StartStep
			fileContent.StartingStep = &initialState.StartStep
		}

		if fileContent.StartingRuntimeMs != nil {
			result.StartRuntime = time.Millisecond *
				time.Duration(*fileContent.StartingRuntimeMs)
		} else {
			result.StartRuntime = initialState.StartRuntime
			millis := initialState.StartRuntime.Milliseconds()
			fileContent.StartingRuntimeMs = &millis
		}

		updated, err := json.Marshal(fileContent)
		if err != nil {
			return nil, fmt.Errorf(
				"runsync: failed to encode sync state file: %v",
				err,
			)
		}

		return updated, nil
	})

	return
}
