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

// Flatten returns a flat list of history items.
//
// The items are ordered by their path, with nested items following their parent.
// If some item cannot be converted to a history item, an error is returned.
func (runHistory *RunHistory) Flatten() ([]*service.HistoryItem, error) {
	leaves := runHistory.PathTree.Flatten()
	history := make([]*service.HistoryItem, len(leaves))
	for i, leaf := range leaves {

		// This should never happen, but it's better to be safe than sorry.
		if len(leaf.Path) == 0 {
			return nil, fmt.Errorf("runhistory: path is empty for item %v", leaf)
		}

		// TODO: would be great to avoid this marshalling
		value, err := pathtree.Marshal(pathtree.FormatJsonExt, leaf.Value)
		if err != nil {
			return nil, err
		}

		history[i] = &service.HistoryItem{
			Key:       leaf.Path[0],
			NestedKey: leaf.Path[1:],
			ValueJson: string(value),
		}
	}
	return history, nil
}
