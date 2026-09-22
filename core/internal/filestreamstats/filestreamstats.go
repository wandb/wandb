// Package filestreamstats measures the cost of the filestream upload pipeline.
//
// Each unit of work is labeled with a `Segment` string and its duration is measured
// and recorded as a histogram. Cell counts are also recorded so they can be used as
// a denominator for latency measurements.
package filestreamstats

import (
	"context"
	"errors"
	"sync/atomic"
	"time"

	"github.com/wandb/wandb/core/internal/analytics"
)

// Segments are named units of work in the upload pipeline.
//
// They are non-overlapping and cover the encode/decode steps of the pipeline.
const (
	// SegmentClientEncode encodes the logged map in the client language.
	// Measured in Python.
	SegmentClientEncode = "client_encode"

	// SegmentHandlerIngest reads logged values into the partial history.
	SegmentHandlerIngest = "handler_ingest"

	// SegmentHandlerEmit converts the partial history back to history items.
	SegmentHandlerEmit = "handler_emit"

	// SegmentTxLogMarshal marshals a record for the transaction log.
	SegmentTxLogMarshal = "txlog_marshal"

	// SegmentUploadIngest reads history items on the upload path.
	SegmentUploadIngest = "upload_ingest"

	// SegmentUploadRender produces the payload for one history row.
	SegmentUploadRender = "upload_render"

	// SegmentRequestMarshal marshals the request including the body.
	SegmentRequestMarshal = "request_marshal"

	// SegmentRequestCompress compresses the request body.
	SegmentRequestCompress = "request_compress"
)

// Streams are the filestream data streams. The values match the server's
// stream tag, so client and server series can be compared directly.
const (
	StreamHistory = "history"
	StreamSummary = "summary"
	StreamEvents  = "events"
	StreamLog     = "log"

	// StreamNone is for a segment that belongs to the request rather than
	// to one stream, such as marshaling or compressing the body. A request
	// carries several streams at once, so no single one owns that cost.
	//
	// An empty attribute is dropped, so these records carry no stream tag.
	StreamNone = ""
)

// Value encodings describe what was written for a history value.
const (
	ValueEncodingJSON      = "json"
	ValueEncodingTyped     = "typed"
	ValueEncodingJSONTyped = "json_typed"
)

// Wire encodings describe the upload payload format.
const (
	WireEncodingJSONL   = "jsonl"
	WireEncodingProtoV1 = "proto_v1"
)

// Content encodings describe the request body encoding.
const (
	ContentEncodingRaw  = "raw"
	ContentEncodingGzip = "gzip"
)

// Metric names. The convention is
// <application>.<subsystem>.<entity>.<measurement>.
const (
	MetricEncodeDuration    = "wandb.filestream.encode.duration"
	MetricEncodeDurationSum = "wandb.filestream.encode.duration.sum"
	MetricRunCount          = "wandb.filestream.run.count"
	MetricRequestSize       = "wandb.filestream.request.size"
	MetricRequestCount      = "wandb.filestream.request.count"
	MetricCellCount         = "wandb.filestream.cell.count"
	MetricTxLogSize         = "wandb.txlog.file.size"
)

func defineHistograms(recorder *analytics.TelemetryRecorder) error {
	return errors.Join(
		recorder.DefineHistogram(
			MetricEncodeDuration,
			analytics.UnitMicroseconds,
			"Time spent encoding run data for upload.",
			[]float64{
				100, 250, 500,
				1_000, 2_500, 5_000,
				10_000, 25_000, 50_000,
				100_000, 250_000, 500_000,
				1_000_000, 2_500_000, 5_000_000,
				30_000_000, 60_000_000, 300_000_000, 900_000_000,
				1_800_000_000, 3_600_000_000, 10_800_000_000, 36_000_000_000,
			},
		),
		recorder.DefineHistogram(
			MetricEncodeDurationSum,
			analytics.UnitMicroseconds,
			"Sum of all segment durations for a run.",
			[]float64{
				100, 250, 500,
				1_000, 2_500, 5_000,
				10_000, 25_000, 50_000,
				100_000, 250_000, 500_000,
				1_000_000, 2_500_000, 5_000_000,
				30_000_000, 60_000_000, 300_000_000, 900_000_000,
				1_800_000_000, 3_600_000_000, 10_800_000_000, 36_000_000_000,
			},
		),
		recorder.DefineHistogram(
			MetricRequestSize,
			analytics.UnitBytes,
			"Size of one filestream request body.",
			[]float64{
				1 << 10, 4 << 10, 16 << 10, 64 << 10, 256 << 10,
				1 << 20, 4 << 20, 16 << 20, 64 << 20, 256 << 20,
			},
		),
		recorder.DefineHistogram(
			MetricCellCount,
			analytics.UnitCount,
			"Logged values in one run.",
			[]float64{
				1, 10, 100, 1000, 10_000,
				100_000, 1_000_000, 5_000_000, 25_000_000,
			},
		),
		recorder.DefineHistogram(
			MetricTxLogSize,
			analytics.UnitBytes,
			"Size of the transaction log a run wrote.",
			[]float64{
				1 << 20, 10 << 20, 100 << 20,
				1 << 30, 10 << 30, 100 << 30,
			},
		),
	)
}

// encodeSegments are the segments whose durations are accumulated per run.
var encodeSegments = []string{
	SegmentHandlerIngest,
	SegmentHandlerEmit,
	SegmentTxLogMarshal,
	SegmentUploadIngest,
	SegmentUploadRender,
	SegmentRequestMarshal,
	SegmentRequestCompress,
}

var streams = []string{
	StreamHistory,
	StreamSummary,
	StreamEvents,
	StreamLog,
	StreamNone,
}

// segmentKey identifies one accumulated duration.
type segmentKey struct {
	segment string
	stream  string
}

// Stats accumulates the pipeline cost of one run and reports it.
//
// A nil *Stats is a no-op. Callers do not need to check for one.
type Stats struct {
	recorder *analytics.TelemetryRecorder

	// valueEncoding is what the run writes for a history value.
	valueEncoding string

	// wireEncoding is the payload format in use. It can change mid-run when
	// a server rejects the typed format, so reads must be atomic.
	wireEncoding atomic.Pointer[string]

	// encodeNanos holds one accumulator per segment and stream. The map is
	// built once and never written to again, so concurrent reads are safe.
	encodeNanos map[segmentKey]*atomic.Int64

	cells     atomic.Int64
	txLogSize atomic.Int64

	requests atomic.Int64
}

// New returns a Stats that reports through the given recorder.
//
// Returns an error if the histograms cannot be defined.
func New(
	recorder *analytics.TelemetryRecorder,
	valueEncoding string,
	wireEncoding string,
) (*Stats, error) {
	encodeNanos := make(
		map[segmentKey]*atomic.Int64,
		len(encodeSegments)*len(streams),
	)
	for _, segment := range encodeSegments {
		for _, stream := range streams {
			encodeNanos[segmentKey{segment, stream}] = &atomic.Int64{}
		}
	}

	stats := &Stats{
		recorder:      recorder,
		valueEncoding: valueEncoding,
		encodeNanos:   encodeNanos,
	}
	stats.wireEncoding.Store(&wireEncoding)
	return stats, defineHistograms(recorder)
}

// WireEncoding returns the payload format currently in use.
func (s *Stats) WireEncoding() string {
	if s == nil {
		return ""
	}
	return *s.wireEncoding.Load()
}

// SetWireEncoding records that the run switched payload format, which happens
// when a server rejects the typed format and the run downgrades to JSONL.
func (s *Stats) SetWireEncoding(wireEncoding string) {
	if s == nil {
		return
	}
	s.wireEncoding.Store(&wireEncoding)
}

// RecordSegment reports one execution of an encode segment and adds it to the
// run's total for that segment.
func (s *Stats) RecordSegment(
	ctx context.Context,
	segment string,
	stream string,
	duration time.Duration,
) {
	if s == nil {
		return
	}

	if total, ok := s.encodeNanos[segmentKey{segment, stream}]; ok {
		total.Add(int64(duration))
	}
}

// AddRow adds one history row to the run's totals.
func (s *Stats) AddRow(cells int) {
	if s == nil {
		return
	}
	s.cells.Add(int64(cells))
}

// SetTxLogBytes records how large the transaction log has grown.
func (s *Stats) SetTxLogBytes(offset int64) {
	if s == nil {
		return
	}
	s.txLogSize.Store(offset)
}

// RequestReport is one filestream request's measurements.
type RequestReport struct {
	// UncompressedBytes and CompressedBytes are the body size before and
	// after compression. They are equal when the body was not compressed.
	UncompressedBytes int
	CompressedBytes   int

	// Compressed reports whether the body was gzipped.
	Compressed bool

	// HTTPDuration is the request itself, retries included.
	HTTPDuration time.Duration
}

// RecordRequest reports one filestream request that carried data.
func (s *Stats) RecordRequest(ctx context.Context, report RequestReport) {
	if s == nil {
		return
	}

	s.requests.Add(1)

	wireEncoding := s.WireEncoding()
	contentEncoding := ContentEncodingRaw
	if report.Compressed {
		contentEncoding = ContentEncodingGzip
	}

	s.recorder.IncrementCounter(
		ctx,
		MetricRequestCount,
		&analytics.LowCardinalityAttributes{
			WireEncoding: wireEncoding,
		},
	)

	s.recorder.RecordHistogram(
		ctx,
		MetricRequestSize,
		float64(report.CompressedBytes),
		&analytics.LowCardinalityAttributes{
			WireEncoding:    wireEncoding,
			ContentEncoding: contentEncoding,
		},
	)
	// The uncompressed size is what the encode work produced, so it is
	// reported even when the body went out compressed.
	if report.Compressed {
		s.recorder.RecordHistogram(
			ctx,
			MetricRequestSize,
			float64(report.UncompressedBytes),
			&analytics.LowCardinalityAttributes{
				WireEncoding:    wireEncoding,
				ContentEncoding: ContentEncodingRaw,
			},
		)
	}
}

// RecordRun reports the run's totals.
func (s *Stats) RecordRun(ctx context.Context) {
	if s == nil {
		return
	}

	wireEncoding := s.WireEncoding()
	encodingAttrs := analytics.LowCardinalityAttributes{
		ValueEncoding: s.valueEncoding,
		WireEncoding:  wireEncoding,
	}

	var totalNanos int64
	for key, accumulated := range s.encodeNanos {
		nanos := accumulated.Load()
		if nanos == 0 {
			continue
		}
		totalNanos += nanos
		attrs := encodingAttrs
		attrs.Segment = key.segment
		attrs.Stream = key.stream
		s.recorder.RecordDuration(
			ctx,
			MetricEncodeDuration,
			time.Duration(nanos),
			&attrs,
		)
	}

	cells := s.cells.Load()
	if cells == 0 && s.requests.Load() == 0 && totalNanos == 0 {
		return
	}

	totalAttrs := encodingAttrs
	s.recorder.RecordDuration(
		ctx,
		MetricEncodeDurationSum,
		time.Duration(totalNanos),
		&totalAttrs,
	)

	countAttrs := analytics.LowCardinalityAttributes{
		Stream:       StreamHistory,
		WireEncoding: wireEncoding,
	}
	s.recorder.RecordHistogram(ctx, MetricCellCount, float64(cells), &countAttrs)

	if txLogSize := s.txLogSize.Load(); txLogSize > 0 {
		s.recorder.RecordHistogram(
			ctx,
			MetricTxLogSize,
			float64(txLogSize),
			&analytics.LowCardinalityAttributes{
				ValueEncoding: s.valueEncoding,
			},
		)
	}

	// The run counter is the denominator for every per-run rate.
	s.recorder.IncrementCounter(ctx, MetricRunCount, &encodingAttrs)
}
