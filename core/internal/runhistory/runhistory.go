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

func (runHistory *RunHistory) ApplyChangeRecord(
	items []*service.HistoryItem,
	onError func(error),
) {
	runHistory.ApplyUpdate(items, onError)
}

// TODO: fix this to build nested tree
func (runHistory *RunHistory) FlattenTree() []*service.HistoryItem {
	var update []*service.HistoryItem
	for key, val := range runHistory.Tree() {
		value, _ := json.Marshal(val)
		update = append(update, &service.HistoryItem{
			Key:       key,
			ValueJson: string(value),
		})
	}

	return update
}
