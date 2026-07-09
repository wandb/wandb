package runsync

import (
	"encoding/json"
	"fmt"
	"io"

	"github.com/rogpeppe/go-internal/lockedfile"
)

// syncStateSuffix is appended to a .wandb file's path to get the path of
// its sync state sidecar file.
const syncStateSuffix = ".syncstate"

// SyncState is the mutable, on-disk state for one .wandb file's sync
// history.
//
// Unlike the write-once ".synced" marker, this file is read and
// potentially rewritten on every sync attempt.
type SyncState struct {
	// StartingStep is the run history step initialized in the first time this
	// file's run was successfully synced with resume reconciliation.
	//
	// Reused on subsequent syncs so that re-syncing the same file doesn't
	// shift step numbers forward each time.
	StartingStep *int64 `json:"starting_step,omitempty"`
}

// SyncStateStore reads and updates the sync state sidecar file for a
// single .wandb file.
type SyncStateStore struct {
	// path is the path to the sidecar file, not the .wandb file itself.
	path string
}

// NewSyncStateStore returns a store for the given .wandb file's sync
// state.
func NewSyncStateStore(wandbFilePath string) *SyncStateStore {
	return &SyncStateStore{path: wandbFilePath + syncStateSuffix}
}

// GetOrInitStartingStep returns the starting step previously initialized, if any.
//
// Otherwise, it persists startingStep so that future calls (including from
// other processes) return the same value.
//
// The read-check-write is performed under an exclusive file lock so that
// concurrent syncs of the same file can't race.
func (s *SyncStateStore) GetOrInitStartingStep(
	startingStep int64,
) (int64, error) {
	f, err := lockedfile.Edit(s.path)
	if err != nil {
		return 0, fmt.Errorf("runsync: failed to lock sync state file: %v", err)
	}
	defer f.Close()

	data, err := io.ReadAll(f)
	if err != nil {
		return 0, fmt.Errorf("runsync: failed to read sync state file: %v", err)
	}

	var state SyncState
	if len(data) > 0 {
		if err := json.Unmarshal(data, &state); err != nil {
			return 0, fmt.Errorf("runsync: failed to parse sync state file: %v", err)
		}
	}

	if state.StartingStep != nil {
		return *state.StartingStep, nil
	}

	state.StartingStep = &startingStep

	updated, err := json.Marshal(state)
	if err != nil {
		return 0, fmt.Errorf("runsync: failed to encode sync state file: %v", err)
	}

	if err := f.Truncate(0); err != nil {
		return 0, fmt.Errorf("runsync: failed to truncate sync state file: %v", err)
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		return 0, fmt.Errorf("runsync: failed to seek sync state file: %v", err)
	}
	if _, err := f.Write(updated); err != nil {
		return 0, fmt.Errorf("runsync: failed to write sync state file: %v", err)
	}

	return startingStep, nil
}
