package leet

import (
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/ansi"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
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

// InspectorInitMsg carries a successfully opened inspector store.
type InspectorInitMsg struct {
	Store *InspectorStore
}

// InspectorBatchMsg carries newly scanned record entries.
type InspectorBatchMsg struct {
	Entries []RecordEntry

	// AtEOF is true when the scan caught up with the end of the
	// currently written data.
	AtEOF bool
}

// InspectorStore indexes a possibly still-written .wandb file for the
// record inspector.
//
// A scan reader advances through the file building the record index while
// a separate detail reader re-reads individual records by offset, so
// browsing never disturbs the scan position.
type InspectorStore struct {
	scanMu   sync.Mutex
	scan     *transactionlog.Reader
	nextNum  int
	corrupt  int
	exitSeen bool
	exitCode int32

	detailMu sync.Mutex
	detail   *transactionlog.Reader

	logger *observability.CoreLogger
}

// NewInspectorStore opens the .wandb file at path for inspection.
func NewInspectorStore(
	path string,
	logger *observability.CoreLogger,
) (*InspectorStore, error) {
	scan, err := transactionlog.OpenReader(path, logger)
	if err != nil {
		return nil, fmt.Errorf("inspectorstore: failed opening reader: %w", err)
	}

	detail, err := transactionlog.OpenReader(path, logger)
	if err != nil {
		scan.Close()
		return nil, fmt.Errorf("inspectorstore: failed opening reader: %w", err)
	}

	return &InspectorStore{
		scan:    scan,
		nextNum: 1,
		detail:  detail,
		logger:  logger,
	}, nil
}

// InitializeInspectorStore returns a command that opens an inspector store
// for the given .wandb file.
func InitializeInspectorStore(
	path string,
	logger *observability.CoreLogger,
) tea.Cmd {
	return func() tea.Msg {
		store, err := NewInspectorStore(path, logger)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InspectorInitMsg{Store: store}
	}
}

// ReadInspectorBatch returns a command that scans the next batch of records.
func ReadInspectorBatch(store *InspectorStore) tea.Cmd {
	return func() tea.Msg {
		entries, atEOF, err := store.ScanBatch(
			LiveMonitorChunkSize,
			LiveMonitorMaxTime,
		)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InspectorBatchMsg{Entries: entries, AtEOF: atEOF}
	}
}

// ScanBatch reads up to maxRecords records or until maxTime elapses,
// whichever comes first, and returns their index entries.
//
// The returned atEOF is true when the scan reached the end of the data
// written so far; calling ScanBatch again later picks up records appended
// in the meantime. Corrupt regions are skipped and counted.
func (s *InspectorStore) ScanBatch(
	maxRecords int,
	maxTime time.Duration,
) (entries []RecordEntry, atEOF bool, err error) {
	s.scanMu.Lock()
	defer s.scanMu.Unlock()

	if s.scan == nil {
		return nil, true, errors.New("inspectorstore: store is closed")
	}

	start := time.Now()
	for len(entries) < maxRecords && time.Since(start) < maxTime {
		offset := s.scan.NextRecordOffset()

		record, readErr := s.scan.Read()
		if readErr != nil {
			if errors.Is(readErr, io.EOF) ||
				errors.Is(readErr, io.ErrUnexpectedEOF) {
				// Rewind so a future scan retries once more data
				// has been written.
				if resetErr := s.scan.ResetLastRead(); resetErr != nil {
					return entries, true, resetErr
				}
				return entries, true, nil
			}
			// Corrupt data: Read already recovered past it; keep going.
			s.corrupt++
			s.logger.Warn(fmt.Sprintf(
				"inspectorstore: skipping corrupt data: %v", readErr))
			continue
		}

		if exit, ok := record.RecordType.(*spb.Record_Exit); ok {
			s.exitSeen = true
			s.exitCode = exit.Exit.GetExitCode()
		}

		entries = append(entries, RecordEntry{
			Num:     s.nextNum,
			Offset:  offset,
			Type:    recordTypeName(record),
			Summary: recordSummary(record),
		})
		s.nextNum++
	}

	return entries, false, nil
}

// RecordAt re-reads the record at the given offset.
func (s *InspectorStore) RecordAt(offset int64) (*spb.Record, error) {
	s.detailMu.Lock()
	defer s.detailMu.Unlock()

	if s.detail == nil {
		return nil, errors.New("inspectorstore: store is closed")
	}
	if err := s.detail.SeekRecord(offset); err != nil {
		return nil, err
	}
	return s.detail.Read()
}

// ExitSeen reports whether an exit record was scanned and its exit code.
func (s *InspectorStore) ExitSeen() (bool, int32) {
	s.scanMu.Lock()
	defer s.scanMu.Unlock()
	return s.exitSeen, s.exitCode
}

// CorruptCount returns the number of corrupt regions skipped so far.
func (s *InspectorStore) CorruptCount() int {
	s.scanMu.Lock()
	defer s.scanMu.Unlock()
	return s.corrupt
}

// Close closes the underlying readers.
func (s *InspectorStore) Close() {
	s.scanMu.Lock()
	if s.scan != nil {
		s.scan.Close()
		s.scan = nil
	}
	s.scanMu.Unlock()

	s.detailMu.Lock()
	if s.detail != nil {
		s.detail.Close()
		s.detail = nil
	}
	s.detailMu.Unlock()
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
