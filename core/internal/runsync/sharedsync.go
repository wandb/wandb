package runsync

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

const sharedSyncRejectedUserText = "Cannot sync a shared-mode run from a transaction log." +
	" Shared mode requires a live server connection." +
	" Re-syncing the same `.wandb` file can duplicate metrics." +
	" Use `--include-shared` to override."

// SharedSyncRejectedUserText returns the user-facing error for rejected shared sync.
func SharedSyncRejectedUserText() string {
	return sharedSyncRejectedUserText
}

// rejectSharedSync returns a SyncError if the run is flagged as shared and
// the caller has not opted in to syncing shared-mode logs.
func rejectSharedSync(
	run *spb.RunRecord,
	allowSharedSync bool,
) error {
	if allowSharedSync || run == nil || !run.GetShared() {
		return nil
	}

	return &SyncError{
		Message:  "runsync: shared-mode transaction log",
		UserText: sharedSyncRejectedUserText,
	}
}
