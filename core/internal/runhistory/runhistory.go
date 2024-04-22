package runhistory

import (
	"encoding/json"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunHistoryDict = pathtree.TreeData

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

func NewFrom(tree RunHistoryDict) *RunHistory {
	return &RunHistory{PathTree: pathtree.NewFrom[*service.HistoryItem](tree)}
}

// TODO: fix this to build nested tree
func (runHistory *RunHistory) FlattenTree() []*service.HistoryItem {
	var items []*service.HistoryItem
	for _, item := range runHistory.Flatten() {
		val, _ := json.Marshal(item.ValueJson)
		history := &service.HistoryItem{
			Key:       item.Key,
			NestedKey: item.NestedKey,
			ValueJson: string(val),
		}
		items = append(items, history)
	}
	return items
}
