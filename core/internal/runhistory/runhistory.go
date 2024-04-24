package runhistory

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunHistory struct {
	*pathtree.PathTree[*service.HistoryItem]
	Step int64
}

func New() *RunHistory {
	return &RunHistory{
		PathTree: pathtree.New[*service.HistoryItem](),
	}
}

func NewWithStep(step int64) *RunHistory {
	return &RunHistory{
		PathTree: pathtree.New[*service.HistoryItem](),
		Step:     step,
	}
}

func (runHistory *RunHistory) ApplyUpdate(
	item []*service.HistoryItem,
	onError func(error),
) {
	runHistory.PathTree.ApplyUpdate(item, onError, pathtree.FormatJsonExt)
}

// Serializes the object to send to the backend.
func (runHistory *RunHistory) Serialize(format pathtree.Format) ([]byte, error) {
	return runHistory.PathTree.Serialize(format, func(value any) any {
		return value
	})
}

func (runHistory *RunHistory) Flatten() ([]*service.HistoryItem, error) {
	items, err := runHistory.PathTree.Flatten(pathtree.FormatJsonExt)
	if err != nil {
		return nil, err
	}
	history := make([]*service.HistoryItem, len(items))
	for i, item := range items {
		value, ok := item.Value.([]byte)
		if !ok {
			return nil, fmt.Errorf("runhistory: expected value to be []byte, got %T", item.Value)
		}
		history[i] = &service.HistoryItem{
			Key:       item.Path[0],
			NestedKey: item.Path[1:],
			ValueJson: string(value),
		}
	}
	return history, nil
}
