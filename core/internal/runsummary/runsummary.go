package runsummary

import (
	"fmt"

	json "github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunSummary struct {
	*pathtree.PathTree[*service.SummaryItem]
}

func New() *RunSummary {
	return &RunSummary{PathTree: pathtree.New[*service.SummaryItem]()}
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rs *RunSummary) ApplyChangeRecord(
	summaryRecord *service.SummaryRecord,
	onError func(error),
) {
	update := summaryRecord.GetUpdate()
	rs.ApplyUpdate(update, onError)

	remove := summaryRecord.GetRemove()
	rs.ApplyRemove(remove, onError)
}

func (rs *RunSummary) Serialize(format pathtree.Format) ([]byte, error) {
	return rs.PathTree.Serialize(format, func(value any) any {
		return value
	})
}

func (rs *RunSummary) Flatten() ([]*service.SummaryItem, error) {
	leaves := rs.PathTree.Flatten()

	items := make([]*service.SummaryItem, len(leaves))
	for i, leaf := range leaves {
		// If value is not a TreeData, add it to the leaves slice with the current path
		value, err := json.Marshal(leaf.Value)
		if err != nil {
			// TODO: continue or error out immediately?
			err = fmt.Errorf("runsummary: failed to marshal JSON for key %v: %v", leaf.Key, err)
			return nil, err
		}
		items[i] = &service.SummaryItem{
			Key:       leaf.Key[0],
			NestedKey: leaf.Key[1:],
			ValueJson: string(value),
		}
	}
	return items, nil
}
