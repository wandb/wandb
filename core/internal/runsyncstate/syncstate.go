package runsyncstate

// syncStateSuffix is appended to a .wandb file's path to get the path of
// its sync state file.
const syncStateSuffix = ".syncstate"

// Store reads and updates the run's upload state.
//
// The sync state is usually stored in a file alongside the `.wandb` file
// and may be updated when run data is uploaded to the server, either during
// `wandb sync` or an online run. It ensures that syncing a run is idempotent,
// in particular for resumed runs.
type Store interface {
	// GetOrInitStartingStep returns the run's starting step.
	//
	// If the step hasn't been initialized yet, this initializes it to
	// the given value.
	GetOrInitStartingStep(startingStep int64) (int64, error)
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
