package runhistory

import (
	"fmt"

	json "github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunHistory struct {
	*pathtree.PathTree[*service.HistoryItem]
	Step *int64
}

func New(step *int64) *RunHistory {
	return &RunHistory{
		PathTree: pathtree.New[*service.HistoryItem](),
		Step:     step,
	}
}

// Serializes the object to send to the backend.
func (runHistory *RunHistory) Serialize(format pathtree.Format) ([]byte, error) {
	// A configuration dict in the format expected by the backend.
	return runHistory.PathTree.Serialize(format, func(value any) any {
		return value
	})
}

func (runHistory *RunHistory) Flatten() ([]*service.HistoryItem, error) {
	var items []*service.HistoryItem
	for _, item := range runHistory.PathTree.Flatten() {
		value, err := json.Marshal(item.Value)
		if err != nil {
			// TODO: continue or error out immediately?
			err = fmt.Errorf("runsummary: failed to marshal JSON for key %v: %v", item.Path, err)
			return nil, err
		}
		history := &service.HistoryItem{
			Key:       item.Path[0],
			NestedKey: item.Path[1:],
			ValueJson: string(value),
		}
		items = append(items, history)
	}
	return items, nil
}
