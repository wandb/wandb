package runhistory

import (
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

func (runHistory *RunHistory) Flatten() []*service.HistoryItem {
	var items []*service.HistoryItem
	for _, item := range runHistory.PathTree.Flatten() {
		history := &service.HistoryItem{
			Key:       item.Key[0],
			NestedKey: item.Key[1:],
			ValueJson: item.Value,
		}
		items = append(items, history)
	}
	return items
}
