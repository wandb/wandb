package report

import (
	"github.com/getsentry/sentry-go/internal/ratelimit"
)

// OutcomeKey uniquely identifies an outcome bucket for aggregation.
type OutcomeKey struct {
	Reason   DiscardReason
	Category ratelimit.Category
}

// DiscardedEvent represents a single discard event outcome for the OutcomeKey.
type DiscardedEvent struct {
	Reason   DiscardReason      `json:"reason"`
	Category ratelimit.Category `json:"category"`
	Quantity int64              `json:"quantity"`
}
