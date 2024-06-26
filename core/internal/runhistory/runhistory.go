package runhistory

import (
	"fmt"

	jsonlib "github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

// The current active history of a run.
//
// This is used to store the history of a run, which would be a single history line
// update for a specific step. The history is stored in a tree structure, where
// each node represents a key in the history. The leaves of the tree are the
// actual values of the history.
type RunHistory struct {
	pathTree *pathtree.PathTree
	step     int64
}

func New() *RunHistory {
	return &RunHistory{
		pathTree: pathtree.New(),
	}
}

func NewFrom(tree pathtree.TreeData) *RunHistory {
	return &RunHistory{
		pathTree: pathtree.NewFrom(tree),
	}
}

// NewWithStep creates a new RunHistory with the given step.
//
// The step is the step of the run that this history is for.
func NewWithStep(step int64) *RunHistory {
	return &RunHistory{
		pathTree: pathtree.New(),
		step:     step,
	}
}

func (rh *RunHistory) GetStep() int64 {
	return rh.step
}

// Updates values in the history tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rh *RunHistory) ApplyChangeRecord(
	historyRecord []*service.HistoryItem,
	onError func(error),
) {
	updates := make([]*pathtree.PathItem, 0, len(historyRecord))
	for _, item := range historyRecord {
		var update interface{}
		// custom unmarshal function that handles NaN and +-Inf
		err := jsonlib.Unmarshal([]byte(item.GetValueJson()), &update)
		fmt.Println("err", err, "update", update, "item", item.GetValueJson())
		if err != nil {
			onError(err)
			continue
		}
		updates = append(updates,
			&pathtree.PathItem{
				Path:  keyPath(item),
				Value: update,
			})
	}
	rh.pathTree.ApplyUpdate(updates, onError)
}

// Serialize the object to send to the backend.
//
// The object is serialized to a JSON string.
// This is needed to send the history to the the backend, which expects a JSON
// string.
func (rh *RunHistory) Serialize() ([]byte, error) {
	// A configuration dict in the format expected by the backend.
	value := rh.pathTree.Tree()
	return jsonlib.Marshal(value)
}

// Flatten returns a flat list of history items.
//
// The items are ordered by their path, with nested items following their parent.
// If some item cannot be converted to a history item, an error is returned.
//
// This is needed to send the history to the sender that expects a flat list of
// history items.
func (rh *RunHistory) Flatten() ([]*service.HistoryItem, error) {

	leaves := rh.pathTree.Flatten()

	history := make([]*service.HistoryItem, 0, len(leaves))
	for _, leaf := range leaves {
		pathLen := len(leaf.Path)
		if pathLen == 0 {
			return nil, fmt.Errorf(
				"runhistory: path is empty for item %v", leaf,
			)
		}

		value, err := jsonlib.Marshal(leaf.Value)
		if err != nil {
			return nil, fmt.Errorf(
				"runhistory: failed to marshal value for item %v: %v",
				leaf, err,
			)
		}

		if pathLen == 1 {
			history = append(history, &service.HistoryItem{
				Key:       leaf.Path[0],
				ValueJson: string(value),
			})
		} else {
			history = append(history, &service.HistoryItem{
				NestedKey: leaf.Path,
				ValueJson: string(value),
			})
		}
	}

	return history, nil
}

// Clone returns a deep copy of the history tree.
func (rh *RunHistory) Tree() pathtree.TreeData {
	return rh.pathTree.Tree()
}

// keyPath returns the key path for the given config item.
// If the item has a nested key, it returns the nested key.
// Otherwise, it returns a slice with the key.
func keyPath(item *service.HistoryItem) []string {
	if len(item.GetNestedKey()) > 0 {
		return item.GetNestedKey()
	}
	return []string{item.GetKey()}
}
