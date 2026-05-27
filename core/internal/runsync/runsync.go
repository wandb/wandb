// Package runsync implements the `wandb sync` command for uploading a run
// from its .wandb file (aka transaction log).
package runsync

const (
	// printerBufferSize is the maximum number of messages (warnings, errors)
	// to buffer before discarding new ones. The client is expected to read
	// messages frequently, so this does not need to be large.
	printerBufferSize = 128
)
