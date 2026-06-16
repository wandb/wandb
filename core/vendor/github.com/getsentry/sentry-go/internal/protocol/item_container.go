package protocol

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/getsentry/sentry-go/internal/ratelimit"
)

var errNoSerializableItems = errors.New("item container contains no serializable items")

type ItemContainer struct {
	items    []TelemetryItem
	category ratelimit.Category
}

// NewItemContainer constructs a batched envelope producer from buffered telemetry items.
func NewItemContainer(category ratelimit.Category, items []TelemetryItem) ItemContainer {
	return ItemContainer{category: category, items: items}
}

func (b ItemContainer) marshalPayload() ([]byte, int, error) {
	items := make([]json.RawMessage, 0, len(b.items))
	for _, item := range b.items {
		itemPayload, err := json.Marshal(item)
		if err != nil {
			continue
		}
		items = append(items, itemPayload)
	}

	if len(items) == 0 {
		return nil, 0, nil
	}

	wrapper := struct {
		Items []json.RawMessage `json:"items"`
	}{Items: items}

	payload, err := json.Marshal(wrapper)
	if err != nil {
		return nil, 0, err
	}
	return payload, len(items), nil
}

func (b ItemContainer) newEnvelopeItem(itemCount int, payload []byte) (*EnvelopeItem, error) {
	switch b.category {
	case ratelimit.CategoryLog:
		return NewLogItem(itemCount, payload), nil
	case ratelimit.CategoryTraceMetric:
		return NewTraceMetricItem(itemCount, payload), nil
	default:
		return nil, fmt.Errorf("unsupported batched category: %s", b.category)
	}
}

func (b ItemContainer) ToEnvelopeItem() (*EnvelopeItem, error) {
	payload, itemCount, err := b.marshalPayload()
	if err != nil {
		return nil, err
	}
	if len(payload) == 0 {
		return nil, errNoSerializableItems
	}

	return b.newEnvelopeItem(itemCount, payload)
}

func (b ItemContainer) ToEnvelope(header *EnvelopeHeader) (*Envelope, error) {
	item, err := b.ToEnvelopeItem()
	if err != nil {
		return nil, err
	}
	return NewEnvelope(header, item), nil
}

func (b ItemContainer) GetCategory() ratelimit.Category            { return b.category }
func (ItemContainer) GetEventID() string                           { return "" }
func (ItemContainer) GetSdkInfo() *SdkInfo                         { return nil }
func (ItemContainer) GetDynamicSamplingContext() map[string]string { return nil }
