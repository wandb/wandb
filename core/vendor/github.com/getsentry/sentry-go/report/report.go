package report

import (
	"encoding/json"
	"time"

	"github.com/getsentry/sentry-go/internal/protocol"
)

// ClientReport is the payload sent to Sentry for tracking discarded events.
type ClientReport struct {
	Timestamp       time.Time        `json:"timestamp"`
	DiscardedEvents []DiscardedEvent `json:"discarded_events"`
}

// ToEnvelopeItem converts the ClientReport to an envelope item.
func (r *ClientReport) ToEnvelopeItem() (*protocol.EnvelopeItem, error) {
	payload, err := json.Marshal(r)
	if err != nil {
		return nil, err
	}
	return protocol.NewClientReportItem(payload), nil
}
