package runhistory

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunHistory struct {
	*pathtree.PathTree
	Step int64
}

func New() *RunHistory {
	return &RunHistory{
		PathTree: pathtree.New(),
	}
}

func NewWithStep(step int64) *RunHistory {
	return &RunHistory{
		PathTree: pathtree.New(),
		Step:     step,
	}
}

// Updates values in the history tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rh *RunHistory) ApplyChangeRecord(
	historyRecord []*service.HistoryItem,
	onError func(error),
) {
	updates := make([]*pathtree.PathItem, len(historyRecord))
	for i, item := range historyRecord {
		updates[i] = pathtree.FromItem(item)
	}
	rh.PathTree.ApplyUpdate(updates, onError, pathtree.FormatJsonExt)
}

// Serializes the object to send to the backend.
func (rh *RunHistory) Serialize(format pathtree.Format) ([]byte, error) {
	return rh.PathTree.Serialize(format, func(value any) any {
		return value
	})
}

// Flatten returns a flat list of history items.
//
// The items are ordered by their path, with nested items following their parent.
// If some item cannot be converted to a history item, an error is returned.
func (rh *RunHistory) Flatten() ([]*service.HistoryItem, error) {

	leaves, err := rh.PathTree.FlattenAndSerialize(pathtree.FormatJsonExt)
	if err != nil {
		return nil, fmt.Errorf("runhistory: failed to flatten tree: %v", err)
	}

	history := make([]*service.HistoryItem, 0, len(leaves))
	for _, leaf := range leaves {
		switch len(leaf.Path) {
		case 0:
			// This should never happen
			return nil, fmt.Errorf("runhistory: path is empty for item %v", leaf)
		case 1:
			history = append(history, &service.HistoryItem{
				Key:       leaf.Path[0],
				ValueJson: leaf.Value,
			})
		default:
			history = append(history, &service.HistoryItem{
				NestedKey: leaf.Path,
				ValueJson: leaf.Value,
			})
		}
	}

	return history, nil
}
