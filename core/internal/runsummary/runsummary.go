package runsummary

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunSummary struct {
	*pathtree.PathTree
}

func New() *RunSummary {
	return &RunSummary{PathTree: pathtree.New()}
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rs *RunSummary) ApplyChangeRecord(
	summaryRecord *service.SummaryRecord,
	onError func(error),
) {
	updates := make([]*pathtree.PathItem, len(summaryRecord.GetUpdate()))
	for i, item := range summaryRecord.GetUpdate() {
		updates[i] = pathtree.FromItem(item)
	}
	rs.ApplyUpdate(updates, onError, pathtree.FormatJsonExt)

	removes := make([]*pathtree.PathItem, len(summaryRecord.GetRemove()))
	for i, item := range summaryRecord.GetRemove() {
		removes[i] = pathtree.FromItem(item)
	}
	rs.ApplyRemove(removes, onError)
}

// Serialize the summary tree to a byte slice.
//
// The format parameter specifies the serialization format.
func (rs *RunSummary) Serialize(format pathtree.Format) ([]byte, error) {
	return rs.PathTree.Serialize(format, func(value any) any {
		return value
	})
}

// Flatten the summary tree into a slice of SummaryItems.
//
// There is no guarantee for the order of the items in the slice.
// The order of the items is determined by the order of the tree traversal.
// The tree traversal is depth-first but based on a map, so the order is not
// guaranteed.
func (rs *RunSummary) Flatten() ([]*service.SummaryItem, error) {

	leaves, err := rs.PathTree.FlattenAndSerialize(pathtree.FormatJsonExt)
	if err != nil {
		return nil, fmt.Errorf("runsummary: failed to flatten tree: %v", err)
	}

	summary := make([]*service.SummaryItem, 0, len(leaves))
	for _, leaf := range leaves {
		switch len(leaf.Path) {
		case 0:
			// This should never happen
			return nil, fmt.Errorf("runsummary: path is empty for item %v", leaf)
		case 1:
			summary = append(summary, &service.SummaryItem{
				Key:       leaf.Path[0],
				ValueJson: leaf.Value,
			})
		default:
			summary = append(summary, &service.SummaryItem{
				NestedKey: leaf.Path,
				ValueJson: leaf.Value,
			})
		}
	}
	return summary, nil
}
