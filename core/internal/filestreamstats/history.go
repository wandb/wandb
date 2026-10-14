package filestreamstats

import (
	"context"
	"math"

	"github.com/wandb/wandb/core/internal/analytics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	MetricHistoryReadCount      = "wandb.history.read.count"
	MetricHistoryKindCount      = "wandb.history.kind.count"
	MetricHistoryNonfiniteCount = "wandb.history.nonfinite.count"
	MetricHistoryTypedJSONCount = "wandb.history.typed_json.count"
	MetricHistoryTypedJSONBytes = "wandb.history.typed_json.bytes"

	// ValueReadSourceTyped is the value for ValueReadSource when counting reads
	// from `value`.
	ValueReadSourceTyped = "typed"

	// ValueReadSourceJSON is the value for ValueReadSource when counting reads
	// from `value_json`.
	ValueReadSourceJSON = "json"
)

var historyKinds = [...]string{"none", "boolean", "integer", "number", "text", "json"}

// HistoryReadCounts counts successfully decoded items at one read boundary.
type HistoryReadCounts struct {
	Typed int64
	JSON  int64
}

// Add records the source selected by the history reader after it succeeds.
func (c *HistoryReadCounts) Add(item *spb.HistoryItem) {
	if item.GetValue() != nil {
		c.Typed++
	} else {
		c.JSON++
	}
}

// RecordHistoryReads reports reads at one pipeline segment.
func (s *Stats) RecordHistoryReads(ctx context.Context, segment string, counts HistoryReadCounts) {
	if s == nil || s.recorder == nil {
		return
	}
	attrs := analytics.LowCardinalityAttributes{
		Stream:        StreamHistory,
		Segment:       segment,
		ValueEncoding: s.valueEncoding,
	}
	if counts.Typed > 0 {
		attrs.ValueReadSource = ValueReadSourceTyped
		s.recorder.AddToCounter(ctx, MetricHistoryReadCount, counts.Typed, &attrs)
	}
	if counts.JSON > 0 {
		attrs.ValueReadSource = ValueReadSourceJSON
		s.recorder.AddToCounter(ctx, MetricHistoryReadCount, counts.JSON, &attrs)
	}
}

// RecordHistoryEmitted reports the typed alternatives returned by ToRecords.
func (s *Stats) RecordHistoryEmitted(ctx context.Context, items []*spb.HistoryItem) {
	if s == nil || s.recorder == nil {
		return
	}
	var kinds [len(historyKinds)]int64
	var nonfinite, jsonCount, jsonBytes int64
	for _, item := range items {
		if item == nil {
			continue
		}
		switch value := item.GetValue().(type) {
		case *spb.HistoryItem_None:
			kinds[0]++
		case *spb.HistoryItem_Boolean:
			kinds[1]++
		case *spb.HistoryItem_Integer:
			kinds[2]++
		case *spb.HistoryItem_Number:
			kinds[3]++
			if math.IsNaN(value.Number) || math.IsInf(value.Number, 0) {
				nonfinite++
			}
		case *spb.HistoryItem_Text:
			kinds[4]++
		case *spb.HistoryItem_Json:
			kinds[5]++
			jsonCount++
			jsonBytes += int64(len(value.Json))
		}
	}
	attrs := analytics.LowCardinalityAttributes{
		Stream:        StreamHistory,
		Segment:       SegmentHandlerEmit,
		ValueEncoding: s.valueEncoding,
	}
	for i, count := range kinds {
		if count == 0 {
			continue
		}
		attrs.ValueKind = historyKinds[i]
		s.recorder.AddToCounter(ctx, MetricHistoryKindCount, count, &attrs)
	}
	attrs.ValueKind = ""
	if nonfinite > 0 {
		s.recorder.AddToCounter(ctx, MetricHistoryNonfiniteCount, nonfinite, &attrs)
	}
	if jsonCount > 0 {
		s.recorder.AddToCounter(ctx, MetricHistoryTypedJSONCount, jsonCount, &attrs)
		if jsonBytes > 0 {
			s.recorder.AddToCounter(ctx, MetricHistoryTypedJSONBytes, jsonBytes, &attrs)
		}
	}
}
