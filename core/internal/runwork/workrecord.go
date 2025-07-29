package runwork

import (
	"fmt"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// WorkRecord is Work constructed from a generic Record.
//
// This is a remnant of our legacy code structure where all Record
// implementations were contained directly in the Handler and Sender files.
// Both files had large switch statements parsing out the specific Record type.
//
// The Work interface is designed to allow for a single parsing step,
// after which each Record that flows through the pipeline also carries with
// it its own implementation. Each Record type should have a corresponding
// Work struct.
type WorkRecord struct {
	SimpleScheduleMixin
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
	}

	return true
}

// ToRecord implements Work.ToRecord.
func (wr WorkRecord) ToRecord() *spb.Record {
	return wr.Record
}

func (wr WorkRecord) BypassOfflineMode() bool {
	return wr.Record.GetControl().GetAlwaysSend()
}

func (wr WorkRecord) Process(fn func(*spb.Record), _ chan<- *spb.Result) {
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
