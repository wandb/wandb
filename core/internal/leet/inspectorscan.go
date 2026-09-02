package leet

import (
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/ansi"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// maxRecordSummaryLen caps the stored summary text per record so that
// indexing a large transaction log stays cheap.
const maxRecordSummaryLen = 120

// RecordEntry describes one record in a .wandb transaction log.
//
// The record's data is not retained: it is re-read from the file by
// offset when the user selects the entry.
type RecordEntry struct {
	// Num is the record's 1-based position in the file.
	Num int

	// Offset is the record's byte offset, used to re-read it on demand.
	Offset int64

	// Type is the record_type oneof field name, e.g. "history".
	Type string

	// Summary is a short type-specific hint shown next to the type.
	Summary string
}

// InspectorInitMsg carries the inspector's opened transaction log stores.
type InspectorInitMsg struct {
	// RunFile is the resolved path of the .wandb file.
	RunFile string

	// Scan is the sequential reader used to index records.
	Scan *LiveStore

	// Detail is the random-access reader used to re-read the selected
	// record, kept separate so seeking never disturbs the scan position.
	Detail *LiveStore
}

// InspectorBatchMsg carries newly scanned record entries.
type InspectorBatchMsg struct {
	Entries []RecordEntry

	// AtEOF is true when the scan caught up with the end of the
	// currently written data.
	AtEOF bool

	// Corrupt counts corrupt regions skipped during this batch.
	Corrupt int

	// ExitSeen is set when an exit record was scanned; ExitCode is its
	// exit code.
	ExitSeen bool
	ExitCode int32
}

// InitializeInspector returns a command that opens the transaction log for
// inspection. An empty runFile resolves to the latest run in wandbDir,
// exactly like starting LEET in single-run mode.
func InitializeInspector(
	runFile, wandbDir string,
	logger *observability.CoreLogger,
) tea.Cmd {
	return func() tea.Msg {
		path, err := resolveWandbFile(runFile, wandbDir)
		if err != nil {
			return ErrorMsg{Err: err}
		}

		scan, err := NewLiveStore(path, logger)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		detail, err := NewLiveStore(path, logger)
		if err != nil {
			scan.Close()
			return ErrorMsg{Err: err}
		}

		return InspectorInitMsg{RunFile: path, Scan: scan, Detail: detail}
	}
}

// ReadInspectorBatch returns a command that scans the next batch of
// records from the store, numbering them from startNum.
func ReadInspectorBatch(store *LiveStore, startNum int) tea.Cmd {
	return func() tea.Msg {
		var msg InspectorBatchMsg

		start := time.Now()
		for len(msg.Entries) < LiveMonitorChunkSize &&
			time.Since(start) < LiveMonitorMaxTime {
			record, offset, err := store.ReadWithOffset()
			switch {
			case errors.Is(err, io.EOF), errors.Is(err, errLiveStoreClosed):
				msg.AtEOF = true
				return msg
			case err != nil:
				// Corrupt data was skipped; keep scanning.
				msg.Corrupt++
				continue
			}

			if exit, ok := record.RecordType.(*spb.Record_Exit); ok {
				msg.ExitSeen = true
				msg.ExitCode = exit.Exit.GetExitCode()
			}

			msg.Entries = append(msg.Entries, RecordEntry{
				Num:     startNum + len(msg.Entries),
				Offset:  offset,
				Type:    recordTypeName(record),
				Summary: recordSummary(record),
			})
		}

		return msg
	}
}

// recordTypeName returns the record_type oneof field name set on the
// record, e.g. "history". Request records are qualified with the request
// type, e.g. "request/partial_history".
func recordTypeName(record *spb.Record) string {
	name := oneofFieldName(record.ProtoReflect(), "record_type")
	if name == "request" {
		if req := record.GetRequest(); req != nil {
			if sub := oneofFieldName(req.ProtoReflect(), "request_type"); sub != "" {
				return "request/" + sub
			}
		}
	}
	if name == "" {
		return "unknown"
	}
	return name
}

// oneofFieldName returns the name of the field set in the message's oneof,
// or "" if the oneof doesn't exist or none of its fields are set.
func oneofFieldName(m protoreflect.Message, oneof protoreflect.Name) string {
	od := m.Descriptor().Oneofs().ByName(oneof)
	if od == nil {
		return ""
	}
	fd := m.WhichOneof(od)
	if fd == nil {
		return ""
	}
	return string(fd.Name())
}

// recordSummary returns a short type-specific hint for the record list.
func recordSummary(record *spb.Record) string {
	switch t := record.RecordType.(type) {
	case *spb.Record_Run:
		return sanitizeRecordSummary(t.Run.GetRunId())
	case *spb.Record_History:
		return fmt.Sprintf("step %d", historyStep(t.History))
	case *spb.Record_Stats:
		if ts := t.Stats.GetTimestamp(); ts != nil {
			return time.Unix(ts.GetSeconds(), 0).Format("15:04:05")
		}
		return ""
	case *spb.Record_OutputRaw:
		return sanitizeRecordSummary(t.OutputRaw.GetLine())
	case *spb.Record_Output:
		return sanitizeRecordSummary(t.Output.GetLine())
	case *spb.Record_Summary:
		return countSummary(len(t.Summary.GetUpdate()), "item")
	case *spb.Record_Config:
		return countSummary(len(t.Config.GetUpdate()), "key")
	case *spb.Record_Files:
		return countSummary(len(t.Files.GetFiles()), "file")
	case *spb.Record_Metric:
		if name := t.Metric.GetName(); name != "" {
			return sanitizeRecordSummary(name)
		}
		return sanitizeRecordSummary(t.Metric.GetGlobName())
	case *spb.Record_Artifact:
		return sanitizeRecordSummary(t.Artifact.GetName())
	case *spb.Record_UseArtifact:
		return sanitizeRecordSummary(t.UseArtifact.GetName())
	case *spb.Record_Alert:
		return sanitizeRecordSummary(t.Alert.GetTitle())
	case *spb.Record_Exit:
		return fmt.Sprintf("code %d", t.Exit.GetExitCode())
	default:
		return ""
	}
}

// historyStep extracts the step from a history record, falling back to the
// "_step" item for records without an explicit step.
func historyStep(h *spb.HistoryRecord) int64 {
	if step := h.GetStep(); step != nil {
		return step.GetNum()
	}
	for _, item := range h.GetItem() {
		if item.GetKey() != "_step" {
			continue
		}
		v, err := strconv.ParseInt(strings.TrimSpace(item.GetValueJson()), 10, 64)
		if err == nil {
			return v
		}
	}
	return 0
}

func countSummary(n int, noun string) string {
	if n == 1 {
		return "1 " + noun
	}
	return fmt.Sprintf("%d %ss", n, noun)
}

// sanitizeRecordSummary makes text safe for single-line list rendering:
// ANSI escapes and control characters are removed and the result is
// truncated to maxRecordSummaryLen.
func sanitizeRecordSummary(s string) string {
	s = ansi.Strip(s)
	s = strings.Map(func(r rune) rune {
		if r < ' ' || r == 0x7f {
			return ' '
		}
		return r
	}, s)
	s = strings.TrimSpace(s)
	if len(s) > maxRecordSummaryLen {
		if runes := []rune(s); len(runes) > maxRecordSummaryLen {
			s = string(runes[:maxRecordSummaryLen])
		}
	}
	return s
}
