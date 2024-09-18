package runwork

import (
	"fmt"

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
	Process(func(*spb.Record))

	// DebugInfo returns a short string describing the work
	// that can be logged for debugging.
	DebugInfo() string
}

// WorkRecord is a Record proto for the Handler->Sender pipeline.
type WorkRecord struct {
	Record *spb.Record
}

func WorkFromRecord(record *spb.Record) Work {
	return WorkRecord{Record: record}
}

func (wr WorkRecord) Accept(fn func(*spb.Record)) bool {
	fn(wr.Record)

	switch wr.Record.RecordType.(type) {
	case *spb.Record_Exit:
		// The Runtime field is updated on the record before forwarding,
		// and it is forwarded with AlwaysSend and if syncing Local.
		return false
	case *spb.Record_Final:
		// Deprecated.
		return false
	case *spb.Record_Footer:
		// Deprecated.
		return false
	case *spb.Record_Header:
		// The record's VersionInfo gets modified before forwarding.
		return false
	case *spb.Record_NoopLinkArtifact:
		// Deprecated.
		return false
	case *spb.Record_Tbrecord:
		// Never forwarded.
		return false
	case *spb.Record_Request:
		// Requests are not forwarded, but may generate additional work.
		return false
	case *spb.Record_Run:
		// Forwarded with AlwaysSend.
		return false
	}

	return true
}

func (wr WorkRecord) Save(fn func(*spb.Record)) {
	fn(wr.Record)
}

func (wr WorkRecord) BypassOfflineMode() bool {
	return wr.Record.GetControl().GetAlwaysSend()
}

func (wr WorkRecord) Process(fn func(*spb.Record)) {
	fn(wr.Record)
}

func (wr WorkRecord) DebugInfo() string {
	var recordType string
	switch x := wr.Record.RecordType.(type) {
	case *spb.Record_Request:
		recordType = fmt.Sprintf("%T", x.Request.RequestType)
	default:
		recordType = fmt.Sprintf("%T", x)
	}

	return fmt.Sprintf(
		"WorkRecord(%s); Control(%v)",
		recordType, wr.Record.GetControl())
}
