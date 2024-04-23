package runsummary

import (
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"

	json "github.com/wandb/simplejsonext"
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
	leaves := pathtree.Flatten(rs.Tree(), []pathtree.Leaf{}, []string{})
	items := make([]*service.SummaryItem, len(leaves))
	for i, leaf := range leaves {
		value, err := json.Marshal(leaf.Value)
		if err != nil {
			// TODO: continue or error out immediately?
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
