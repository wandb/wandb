package runwork

import (
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Work is a task in the Handler->Sender pipeline.
type Work struct {
	WorkImpl

	// Request is a possibly nil request that resulted in this work.
	//
	// A non-nil Request requires a response. If the Request is cancelled,
	// any tasks that only existed to respond to the Request should be
	// cancelled.
	Request *Request
}

// Accept invokes WorkImpl.Accept with this Work's Request.
func (w Work) Accept(fn func(*spb.Record, *Request)) bool {
	return w.WorkImpl.Accept(w.Request, fn)
}

// Process invokes WorkImpl.Process with this Work's Request.
func (w Work) Process(fn func(*spb.Record, *Request)) {
	w.WorkImpl.Process(w.Request, fn)
}

// NoRequest creates Work without a Request.
//
// It is more explicit than just omitting the Request field, which can
// help readability.
func NoRequest(impl WorkImpl) Work {
	return Work{WorkImpl: impl}
}

// WorkImpl defines the business logic for processing some Work.
type WorkImpl interface {
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
	// The second function is the Handler method containing legacy
	// record-processing code.
	Accept(*Request, func(*spb.Record, *Request)) bool

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
	// The second function is the Sender method containing legacy
	// record-processing code.
	Process(*Request, func(*spb.Record, *Request))

	// DebugInfo returns a short string describing the work
	// that can be logged for debugging.
	DebugInfo() string
}

// MaybeSavedWork is work that may have been written to the transaction log.
//
// Some work (like the work for a Request) is not saved.
//
// This should be passed by value.
type MaybeSavedWork struct {
	Work Work

	// IsSaved is true if the work has been successfully written to the
	// transaction log.
	//
	// Note that the associated Request is never serialized.
	IsSaved bool

	// SavedOffset is the byte offset in the transaction log where the record
	// was written.
	SavedOffset int64

	// RecordNumber is the record's index in the transaction log.
	RecordNumber int64
}

// SimpleScheduleMixin implements WorkImpl.Schedule by immediately invoking
// the callback.
type SimpleScheduleMixin struct{}

func (m SimpleScheduleMixin) Schedule(wg *sync.WaitGroup, proceed func()) {
	proceed()
}

// AlwaysAcceptMixin implements WorkImpl.Accept by returning true.
type AlwaysAcceptMixin struct{}

func (m AlwaysAcceptMixin) Accept(
	*Request,
	func(*spb.Record, *Request),
) bool {
	return true
}

// NoopProcessMixin implements WorkImpl.Process by doing nothing.
//
// Since Process is a no-op, BypassOfflineMode is implemented to return false
type NoopProcessMixin struct{}

func (m NoopProcessMixin) BypassOfflineMode() bool { return false }

func (m NoopProcessMixin) Process(
	*Request,
	func(*spb.Record, *Request),
) {
}
