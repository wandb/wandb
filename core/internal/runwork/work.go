package runwork

import (
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Work is a task in the Handler->Sender pipeline.
type Work interface {
	// Schedule inserts work into the pipeline.
	//
	// This is a step "outside" the pipeline, that happens upon receiving
	// records from the client or reading them from the transaction log.
	// This step can defer record processing until some condition has occurred,
	// without blocking the ingestion of other records---thereby reordering
	// them.
	//
	// The WaitGroup is used to signal when proceed() has been invoked.
	// To prevent deadlocks, it must not block on other work entering
	// the pipeline.
	Schedule(wg *sync.WaitGroup, proceed func())

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

	// ToRecord returns the serialized representation of this Work.
	//
	// The returned value's number may be modified in the Writer goroutine.
	// Otherwise, the value must not be modified.
	ToRecord() *spb.Record

	// BypassOfflineMode reports whether Process needs to happen
	// even if we're offline.
	BypassOfflineMode() bool

	// Process performs the work.
	//
	// If this is a Record proto, the given function is called.
	// Responses are pushed into the Result channel.
	Process(func(*spb.Record), chan<- *spb.Result)

	// DebugInfo returns a short string describing the work
	// that can be logged for debugging.
	DebugInfo() string
}

// SimpleScheduleMixin implements Work.Schedule by immediately invoking
// the callback.
type SimpleScheduleMixin struct{}

func (m SimpleScheduleMixin) Schedule(wg *sync.WaitGroup, proceed func()) {
	proceed()
}

// AlwaysAcceptMixin implements Work.Accept by returning true.
type AlwaysAcceptMixin struct{}

func (m AlwaysAcceptMixin) Accept(func(*spb.Record)) bool { return true }

// NoopProcessMixin implements Work.Process by doing nothing.
//
// Since Process is a no-op, BypassOfflineMode is implemented to return false
type NoopProcessMixin struct{}

func (m NoopProcessMixin) BypassOfflineMode() bool { return false }

func (m NoopProcessMixin) Process(func(*spb.Record), chan<- *spb.Result) {}
