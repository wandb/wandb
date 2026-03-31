package report

import (
	"sync"
	"sync/atomic"
	"time"

	"github.com/getsentry/sentry-go/internal/debuglog"
	"github.com/getsentry/sentry-go/internal/protocol"
	"github.com/getsentry/sentry-go/internal/ratelimit"
)

// Aggregator collects discarded event outcomes for client reports.
// Uses atomic operations to be safe for concurrent use.
type Aggregator struct {
	mu       sync.Mutex
	outcomes map[OutcomeKey]*atomic.Int64
}

// NewAggregator creates a new client report Aggregator.
func NewAggregator() *Aggregator {
	a := &Aggregator{
		outcomes: make(map[OutcomeKey]*atomic.Int64),
	}
	return a
}

// Record records a discarded event outcome.
func (a *Aggregator) Record(reason DiscardReason, category ratelimit.Category, quantity int64) {
	if a == nil || quantity <= 0 {
		return
	}

	key := OutcomeKey{Reason: reason, Category: category}

	a.mu.Lock()
	defer a.mu.Unlock()
	counter, exists := a.outcomes[key]
	if !exists {
		counter = &atomic.Int64{}
		a.outcomes[key] = counter
	}
	counter.Add(quantity)
}

// RecordOne is a helper method to record one discarded event outcome.
func (a *Aggregator) RecordOne(reason DiscardReason, category ratelimit.Category) {
	a.Record(reason, category, 1)
}

// TakeReport atomically takes all accumulated outcomes and returns a ClientReport.
func (a *Aggregator) TakeReport() *ClientReport {
	if a == nil {
		return nil
	}
	a.mu.Lock()
	defer a.mu.Unlock()

	if len(a.outcomes) == 0 {
		return nil
	}

	var events []DiscardedEvent
	for key, counter := range a.outcomes {
		quantity := counter.Swap(0)
		if quantity > 0 {
			events = append(events, DiscardedEvent{
				Reason:   key.Reason,
				Category: key.Category,
				Quantity: quantity,
			})
		}
	}

	// Clear empty counters to prevent unbounded growth
	for key, counter := range a.outcomes {
		if counter.Load() == 0 {
			delete(a.outcomes, key)
		}
	}

	if len(events) == 0 {
		return nil
	}

	return &ClientReport{
		Timestamp:       time.Now(),
		DiscardedEvents: events,
	}
}

// RecordForEnvelope records client report outcomes for all items in the envelope.
// It inspects envelope item headers to derive categories, span counts, and log byte sizes.
func (a *Aggregator) RecordForEnvelope(reason DiscardReason, envelope *protocol.Envelope) {
	if a == nil {
		return
	}

	for _, item := range envelope.Items {
		if item == nil || item.Header == nil {
			continue
		}
		switch item.Header.Type {
		case protocol.EnvelopeItemTypeEvent:
			a.RecordOne(reason, ratelimit.CategoryError)
		case protocol.EnvelopeItemTypeTransaction:
			a.RecordOne(reason, ratelimit.CategoryTransaction)
			spanCount := int64(item.Header.SpanCount)
			a.Record(reason, ratelimit.CategorySpan, spanCount)
		case protocol.EnvelopeItemTypeLog:
			if item.Header.ItemCount != nil {
				a.Record(reason, ratelimit.CategoryLog, int64(*item.Header.ItemCount))
			}
			if item.Header.Length != nil {
				a.Record(reason, ratelimit.CategoryLogByte, int64(*item.Header.Length))
			}
		case protocol.EnvelopeItemTypeTraceMetric:
			a.RecordOne(reason, ratelimit.CategoryTraceMetric)
		case protocol.EnvelopeItemTypeCheckIn:
			a.RecordOne(reason, ratelimit.CategoryMonitor)
		case protocol.EnvelopeItemTypeAttachment, protocol.EnvelopeItemTypeClientReport:
			// Skip — not reportable categories
		}
	}
}

// RecordItem records outcomes for a telemetry item, including supplementary
// categories (span outcomes for transactions, byte size for logs).
func (a *Aggregator) RecordItem(reason DiscardReason, item protocol.TelemetryItem) {
	category := item.GetCategory()
	a.RecordOne(reason, category)

	// Span outcomes for transactions
	if category == ratelimit.CategoryTransaction {
		type spanCounter interface{ GetSpanCount() int }
		if sc, ok := item.(spanCounter); ok {
			if count := sc.GetSpanCount(); count > 0 {
				a.Record(reason, ratelimit.CategorySpan, int64(count))
			}
		}
	}

	// Byte size outcomes for logs
	if category == ratelimit.CategoryLog {
		type sizer interface{ ApproximateSize() int }
		if s, ok := item.(sizer); ok {
			if size := s.ApproximateSize(); size > 0 {
				a.Record(reason, ratelimit.CategoryLogByte, int64(size))
			}
		}
	}
}

// AttachToEnvelope adds a client report to the envelope if the Aggregator has outcomes available.
func (a *Aggregator) AttachToEnvelope(envelope *protocol.Envelope) {
	if a == nil {
		return
	}

	r := a.TakeReport()
	if r != nil {
		rItem, err := r.ToEnvelopeItem()
		if err == nil {
			envelope.AddItem(rItem)
		} else {
			debuglog.Printf("failed to serialize client report: %v, with err: %v", r, err)
		}
	}
}
