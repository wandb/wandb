package runsyncstate

import "time"

// syncStateSuffix is appended to a .wandb file's path to get the path of
// its sync state file.
const syncStateSuffix = ".syncstate"

// StartState contains starting parameters that are necessary to sync the run
// but that are determined by the server.
type StartState struct {
	// StartStep is the run's initial `_step` value.
	//
	// For new runs, this is zero.
	// For forked runs, this is specified by the user.
	// For resumed runs, this is one more than the previous run's last `_step`.
	StartStep int64

	// StartRuntime is the run's initial `_runtime` value.
	//
	// This is non-zero only for resumed runs, where it is the previous run's
	// last `_runtime`.
	StartRuntime time.Duration
}

// Store reads and updates the run's upload state.
//
// The sync state is usually stored in a file alongside the `.wandb` file
// and may be updated when run data is uploaded to the server, either during
// `wandb sync` or an online run. It ensures that syncing a run is idempotent,
// in particular for resumed runs.
type Store interface {
	// GetOrInitStartState returns the run's starting state.
	//
	// If the start state hasn't been initialized yet, this initializes it to
	// the given value.
	GetOrInitStartState(initialState StartState) (StartState, error)
}

// File returns a Store backed by a `.wandb.syncstate` file.
//
// This uses file-level locking to read and update the file and is meant to work
// when accessed by multiple wandb-core processes at once.
func File(transactionLogPath string) Store {
	return &fileStore{path: transactionLogPath + syncStateSuffix}
}

// InMemory returns an in-memory Store.
func InMemory() Store {
	return &memoryStore{}
}
