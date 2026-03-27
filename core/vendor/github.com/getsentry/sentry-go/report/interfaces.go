package report

import (
	"github.com/getsentry/sentry-go/internal/protocol"
	"github.com/getsentry/sentry-go/internal/ratelimit"
)

// ClientReportRecorder is used by components that need to record lost/discarded events.
type ClientReportRecorder interface {
	Record(reason DiscardReason, category ratelimit.Category, quantity int64)
	RecordOne(reason DiscardReason, category ratelimit.Category)
	RecordForEnvelope(reason DiscardReason, envelope *protocol.Envelope)
	RecordItem(reason DiscardReason, item protocol.TelemetryItem)
}

// ClientReportProvider is used by the single component responsible for sending client reports.
type ClientReportProvider interface {
	TakeReport() *ClientReport
	AttachToEnvelope(envelope *protocol.Envelope)
}

// noopRecorder is a no-op implementation of ClientReportRecorder.
type noopRecorder struct{}

func (noopRecorder) Record(DiscardReason, ratelimit.Category, int64)     {}
func (noopRecorder) RecordOne(DiscardReason, ratelimit.Category)         {}
func (noopRecorder) RecordForEnvelope(DiscardReason, *protocol.Envelope) {}
func (noopRecorder) RecordItem(DiscardReason, protocol.TelemetryItem)    {}

// noopProvider is a no-op implementation of ClientReportProvider.
type noopProvider struct{}

func (noopProvider) TakeReport() *ClientReport             { return nil }
func (noopProvider) AttachToEnvelope(_ *protocol.Envelope) {}

// NoopRecorder returns a no-op ClientReportRecorder that silently discards all records.
func NoopRecorder() ClientReportRecorder { return noopRecorder{} }

// NoopProvider returns a no-op ClientReportProvider that always returns nil reports.
func NoopProvider() ClientReportProvider { return noopProvider{} }
