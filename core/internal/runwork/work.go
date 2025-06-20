package runwork

import (
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Work is a task in the Handler->Sender pipeline.
//
// Most work is in the form of Record protos from the client.
// Occasionally, it is useful to inject additional work that must
// happen in order with Record processing. There are some Records
// that exist only for this purpose, but it is not an appropriate
// use of protos, and it is very limiting.
type Work interface {
	// Accept indicates the work has entered the pipeline.
	//
	// It returns true if the work should continue through the pipeline,
	// and false if all handling was performed.
	//
	// This should return quickly as it blocks the ingestion of further work
	// from the client. If it blocks too long, client operations like
	// `run.log()` can start to block.
	//
	// If this is a Record proto, the given function is called.
	Accept(func(*spb.Record)) bool

	// Save writes the work to the transaction log.
	//
	// If this is a Record proto, the given function is called.
	Save(func(*spb.Record))

	// BypassOfflineMode reports whether Process needs to happen
	// even if we're offline.
	BypassOfflineMode() bool

	// Process performs the work.
	//
	// If this is a Record proto, the given function is called.
	// Responses are pushed into the Result channel.
	Process(func(*spb.Record), chan<- *spb.Result)

	// Sentinel returns the value passed to NewSentinel, or nil.
	//
	// This is used as a synchronization mechanism: by pushing a Sentinel
	// into the work stream and waiting to receive it, one can wait until all
	// work buffered by a certain time has been processed.
	Sentinel() any

	// DebugInfo returns a short string describing the work
	// that can be logged for debugging.
	DebugInfo() string
}
