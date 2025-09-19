// Package transactionlog implements reading and writing .wandb files.
package transactionlog

// wandbStoreVersion is written into .wandb file headers.
//
// Incrementing this prevents older clients from attempting to read .wandb
// files in a new format.
const wandbStoreVersion = 0
