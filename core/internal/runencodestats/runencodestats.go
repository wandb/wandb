// Package runencodestats accumulates the cost of encoding run history.
//
// A logged value is serialized and re-parsed several times between run.log()
// and the filestream request. The Typed History project replaces that pipeline
// with a typed columnar payload. These counters record what the existing JSONL
// pipeline costs on real runs, so the change can be measured against field data
// instead of fixture benchmarks.
package runencodestats

import (
	"strconv"
	"sync/atomic"
	"time"
)

// Stats accumulates encode-path counters for one run.
//
// The hops run in four goroutines (handler, sender, transaction-log writer and
// filestream), so every field is atomic.
//
// A nil *Stats is a no-op. Callers do not need to check for one.
type Stats struct {
	// handlerParseNanos is time spent parsing value_json into the partial
	// history, in the handler.
	handlerParseNanos atomic.Int64

	// handlerRecordsNanos is time spent re-encoding the partial history back
	// into history items, in the handler.
	handlerRecordsNanos atomic.Int64

	// txLogMarshalNanos is time spent marshaling records to protobuf for the
	// transaction log.
	txLogMarshalNanos atomic.Int64

	// senderParseNanos is time spent re-parsing value_json in the sender.
	senderParseNanos atomic.Int64

	// rowRenderNanos is time spent rendering a history row to a JSONL line.
	rowRenderNanos atomic.Int64

	// envelopeNanos is time spent marshaling the filestream request body.
	envelopeNanos atomic.Int64

	// compressNanos is time spent compressing the filestream request body.
	compressNanos atomic.Int64

	rows     atomic.Int64
	cells    atomic.Int64
	rowBytes atomic.Int64

	// skippedOversizeRows counts history rows dropped for exceeding the
	// maximum line size.
	skippedOversizeRows atomic.Int64

	requests          atomic.Int64
	heartbeats        atomic.Int64
	gzipRequests      atomic.Int64
	uncompressedBytes atomic.Int64
	compressedBytes   atomic.Int64
}

// New returns a new, zeroed Stats.
func New() *Stats {
	return &Stats{}
}

// AddHandlerParse records time spent parsing history items in the handler.
func (s *Stats) AddHandlerParse(d time.Duration) {
	if s == nil {
		return
	}
	s.handlerParseNanos.Add(int64(d))
}

// AddHandlerRecords records time spent converting history back to records.
func (s *Stats) AddHandlerRecords(d time.Duration) {
	if s == nil {
		return
	}
	s.handlerRecordsNanos.Add(int64(d))
}

// AddTxLogMarshal records time spent marshaling a transaction-log record.
func (s *Stats) AddTxLogMarshal(d time.Duration) {
	if s == nil {
		return
	}
	s.txLogMarshalNanos.Add(int64(d))
}

// AddSenderParse records time spent parsing history items in the sender.
func (s *Stats) AddSenderParse(d time.Duration) {
	if s == nil {
		return
	}
	s.senderParseNanos.Add(int64(d))
}

// AddHistoryRow records one history row rendered to a JSONL line.
func (s *Stats) AddHistoryRow(cells int, lineBytes int, d time.Duration) {
	if s == nil {
		return
	}
	s.rows.Add(1)
	s.cells.Add(int64(cells))
	s.rowBytes.Add(int64(lineBytes))
	s.rowRenderNanos.Add(int64(d))
}

// AddSkippedOversizeRow records a history row dropped for being too long.
func (s *Stats) AddSkippedOversizeRow() {
	if s == nil {
		return
	}
	s.skippedOversizeRows.Add(1)
}

// AddRequest records one filestream request that carried data.
//
// compressed equals uncompressed when the request was not compressed.
func (s *Stats) AddRequest(
	uncompressed int,
	compressed int,
	gzip bool,
	encode time.Duration,
	compress time.Duration,
) {
	if s == nil {
		return
	}
	s.requests.Add(1)
	s.uncompressedBytes.Add(int64(uncompressed))
	s.compressedBytes.Add(int64(compressed))
	s.envelopeNanos.Add(int64(encode))
	s.compressNanos.Add(int64(compress))
	if gzip {
		s.gzipRequests.Add(1)
	}
}

// AddHeartbeat records one filestream request that carried no data.
func (s *Stats) AddHeartbeat() {
	if s == nil {
		return
	}
	s.heartbeats.Add(1)
}

// Attributes returns the counters for a telemetry log record.
//
// Every value is a count, a byte size or a duration. No metric name and no
// metric value is included.
//
// Returns nil if there is nothing to report, so the caller can skip the record.
func (s *Stats) Attributes() map[string]string {
	if s == nil {
		return nil
	}

	rows := s.rows.Load()
	requests := s.requests.Load()
	heartbeats := s.heartbeats.Load()
	skipped := s.skippedOversizeRows.Load()

	if rows == 0 && requests == 0 && heartbeats == 0 && skipped == 0 {
		return nil
	}

	return map[string]string{
		"format": "jsonl",

		"handler_parse_nanos":   itoa(s.handlerParseNanos.Load()),
		"handler_records_nanos": itoa(s.handlerRecordsNanos.Load()),
		"txlog_marshal_nanos":   itoa(s.txLogMarshalNanos.Load()),
		"sender_parse_nanos":    itoa(s.senderParseNanos.Load()),
		"row_render_nanos":      itoa(s.rowRenderNanos.Load()),
		"envelope_nanos":        itoa(s.envelopeNanos.Load()),
		"compress_nanos":        itoa(s.compressNanos.Load()),

		"rows":                  itoa(rows),
		"cells":                 itoa(s.cells.Load()),
		"row_bytes":             itoa(s.rowBytes.Load()),
		"skipped_oversize_rows": itoa(skipped),

		"requests":           itoa(requests),
		"heartbeats":         itoa(heartbeats),
		"gzip_requests":      itoa(s.gzipRequests.Load()),
		"uncompressed_bytes": itoa(s.uncompressedBytes.Load()),
		"compressed_bytes":   itoa(s.compressedBytes.Load()),
	}
}

func itoa(v int64) string {
	return strconv.FormatInt(v, 10)
}
