// Package transactionlog implements reading and writing .wandb files.
package transactionlog

// wandbStoreVersion is the format version byte written into new .wandb headers.
//
// Version 1 accompanies wandb PR #12110's history-step on-disk change: auto-
// step rows no longer materialize record.Step, a "_step" item, or summary
// "_step" at write time. Incrementing this prevents older clients from
// attempting to read files in the new format; current readers accept both
// minSupportedWandbStoreVersion and wandbStoreVersion.
const wandbStoreVersion = 1

// minSupportedWandbStoreVersion is the oldest header version current readers
// accept. Version 0 files use the pre-PR history-step encoding.
const minSupportedWandbStoreVersion = 0
