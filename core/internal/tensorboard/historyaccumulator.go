package tensorboard

import (
	"fmt"
	"strings"

	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/service"
)

// HistoryAccumulator converts TF events into W&B history data.
type HistoryAccumulator struct {
	// started is whether at least one event has been accumulated.
	started bool

	// step is the current TF step number.
	step int64

	// data is a map from TF tags to values.
	data map[string]float32
}

// Add updates the accumulated run history from the TF event.
//
// If this event belongs to a new step, the accumulated data for the previous
// step is returned.
func (h *HistoryAccumulator) Add(
	event *tbproto.TFEvent,
) (ret *service.HistoryRecord) {
	if !h.started {
		h.data = make(map[string]float32)
	} else if event.Step != h.step {
		ret = toHistoryRecord(h.data)
		h.data = make(map[string]float32)
	}

	// TODO: Use separate steps for separate "namespaces".
	h.step = event.Step
	h.started = true

	for _, value := range event.GetSummary().GetValue() {
		tag := value.GetTag()

		switch value := value.GetValue().(type) {
		case *tbproto.Summary_Value_SimpleValue:
			// TODO: Use namespaced tags.
			h.data[tag] = value.SimpleValue
		}
	}

	return
}

func toHistoryRecord(data map[string]float32) *service.HistoryRecord {
	items := make([]*service.HistoryItem, 0)

	for tag, value := range data {
		items = append(items, &service.HistoryItem{
			NestedKey: strings.Split(tag, "/"),
			ValueJson: fmt.Sprintf("%v", value),
		})
	}

	// We intentionally don't set a step.
	// TODO: understand why
	return &service.HistoryRecord{Item: items}
}
