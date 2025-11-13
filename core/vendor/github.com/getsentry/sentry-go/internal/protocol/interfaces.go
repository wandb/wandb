package protocol

import (
	"context"
	"time"

	"github.com/getsentry/sentry-go/internal/ratelimit"
)

// EnvelopeConvertible represents any type that can be converted to a Sentry envelope.
// This interface allows the telemetry buffers to be generic while still working with
// concrete types like Event.
type EnvelopeConvertible interface {
	// ToEnvelope converts the item to a Sentry envelope.
	ToEnvelope(dsn *Dsn) (*Envelope, error)
}

// TelemetryTransport represents the envelope-first transport interface.
// This interface is designed for the telemetry buffer system and provides
// non-blocking sends with backpressure signals.
type TelemetryTransport interface {
	// SendEnvelope sends an envelope to Sentry. Returns immediately with
	// backpressure error if the queue is full.
	SendEnvelope(envelope *Envelope) error

	// SendEvent sends an event to Sentry.
	SendEvent(event EnvelopeConvertible)

	// IsRateLimited checks if a specific category is currently rate limited
	IsRateLimited(category ratelimit.Category) bool

	// Flush waits for all pending envelopes to be sent, with timeout
	Flush(timeout time.Duration) bool

	// FlushWithContext waits for all pending envelopes to be sent
	FlushWithContext(ctx context.Context) bool

	// Close shuts down the transport gracefully
	Close()
}
