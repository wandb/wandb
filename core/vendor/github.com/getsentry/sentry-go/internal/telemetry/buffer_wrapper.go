package telemetry

import (
	"context"
	"time"

	"github.com/getsentry/sentry-go/internal/protocol"
	"github.com/getsentry/sentry-go/internal/ratelimit"
)

// Buffer is the top-level buffer that wraps the scheduler and category buffers.
type Buffer struct {
	scheduler *Scheduler
}

// NewBuffer creates a new Buffer with the given configuration.
func NewBuffer(
	storage map[ratelimit.Category]Storage[protocol.EnvelopeItemConvertible],
	transport protocol.TelemetryTransport,
	dsn *protocol.Dsn,
	sdkInfo *protocol.SdkInfo,
) *Buffer {
	scheduler := NewScheduler(storage, transport, dsn, sdkInfo)
	scheduler.Start()

	return &Buffer{
		scheduler: scheduler,
	}
}

// Add adds an EnvelopeItemConvertible to the appropriate buffer based on its category.
func (b *Buffer) Add(item protocol.EnvelopeItemConvertible) bool {
	return b.scheduler.Add(item)
}

// Flush forces all buffers to flush within the given timeout.
func (b *Buffer) Flush(timeout time.Duration) bool {
	return b.scheduler.Flush(timeout)
}

// FlushWithContext flushes with a custom context for cancellation.
func (b *Buffer) FlushWithContext(ctx context.Context) bool {
	return b.scheduler.FlushWithContext(ctx)
}

// Close stops the buffer, flushes remaining data, and releases resources.
func (b *Buffer) Close(timeout time.Duration) {
	b.scheduler.Stop(timeout)
}
