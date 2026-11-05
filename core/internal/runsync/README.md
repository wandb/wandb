# Run sync

This package uploads transaction logs for `wandb sync` and `wandb beta sync`. `RunReader` reads
records and waits for the exit request to finish; `Sender` handles uploads.
`RunSyncer.Sync` writes the `.synced` marker only after both return successfully
and the caller's context is still active.

A fatal filestream error is returned through `Sender.FileStreamError`. It
prevents a new marker and the `Finished syncing` message. Marker write errors
also fail the operation. Existing markers from earlier attempts are unchanged.

This is not a complete delivery guarantee: file and artifact upload failures
are not yet propagated through this result, and a filestream success does not
prove downstream storage visibility. This package does not implement automatic
replay on resume or new server deduplication semantics.
