package filestream

import (
	"encoding/json"
	"fmt"
	"strconv"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// EventUpdate contains a structured run event.
type EventUpdate struct {
	Record *spb.EventRecord
}

type eventAttribute struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

func (u *EventUpdate) Apply(ctx UpdateContext) error {
	event := u.Record
	attributes := make(map[string]eventAttribute, len(event.GetAttributes()))
	for name, attribute := range event.GetAttributes() {
		switch v := attribute.GetValue().(type) {
		case *spb.EventAttributeValue_StringValue:
			attributes[name] = eventAttribute{"string", v.StringValue}
		case *spb.EventAttributeValue_IntValue:
			attributes[name] = eventAttribute{"int64", strconv.FormatInt(v.IntValue, 10)}
		case *spb.EventAttributeValue_DoubleValue:
			attributes[name] = eventAttribute{
				"float64",
				strconv.FormatFloat(v.DoubleValue, 'g', -1, 64),
			}
		case *spb.EventAttributeValue_BoolValue:
			attributes[name] = eventAttribute{"bool", strconv.FormatBool(v.BoolValue)}
		}
	}
	var stepMetric *string
	if event.StepMetricValue != nil {
		stepMetric = &event.StepMetric
	}
	body, err := json.Marshal(struct {
		EventID         string                    `json:"event_id"`
		TimestampMs     int64                     `json:"timestamp_ms"`
		Type            string                    `json:"type"`
		Title           string                    `json:"title"`
		Severity        string                    `json:"severity"`
		Step            int64                     `json:"step"`
		StepMetric      *string                   `json:"step_metric,omitempty"`
		StepMetricValue *float64                  `json:"step_metric_value,omitempty"`
		Attributes      map[string]eventAttribute `json:"attributes"`
	}{
		EventID: event.GetEventId(), TimestampMs: event.GetTimestampMs(),
		Type: event.GetType(), Title: event.GetTitle(), Severity: event.GetSeverity(),
		Step: event.GetStep(), StepMetric: stepMetric,
		StepMetricValue: event.StepMetricValue, Attributes: attributes,
	})
	if err != nil {
		return fmt.Errorf("filestream: failed to serialize event: %v", err)
	}
	ctx.MakeRequest(&FileStreamRequest{Events: []json.RawMessage{body}})
	return nil
}
