package runsummary

import (
	"fmt"

	// TODO: use simplejsonext for now until we replace the usage of json with
	// protocol buffer and proto json marshaler
	json "github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunSummary struct {
	pathTree *pathtree.PathTree
}

func New() *RunSummary {
	return &RunSummary{pathTree: pathtree.New()}
}

func NewFrom(tree pathtree.TreeData) *RunSummary {
	return &RunSummary{pathTree: pathtree.NewFrom(tree)}
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rs *RunSummary) ApplyChangeRecord(
	summaryRecord *service.SummaryRecord,
	onError func(error),
) {

	updates := make([]*pathtree.PathItem, 0, len(summaryRecord.GetUpdate()))
	for _, item := range summaryRecord.GetUpdate() {
		update, err := json.Unmarshal([]byte(item.GetValueJson()))
		if err != nil {
			onError(err)
			continue
		}
		updates = append(updates, &pathtree.PathItem{
			Path:  keyPath(item),
			Value: update,
		})
	}
	rs.pathTree.ApplyUpdate(updates, onError)

	removes := make([]*pathtree.PathItem, 0, len(summaryRecord.GetRemove()))
	for _, item := range summaryRecord.GetRemove() {
		removes = append(removes, &pathtree.PathItem{
			Path: keyPath(item),
		})
	}
	rs.pathTree.ApplyRemove(removes)
}

// Flatten the summary tree into a slice of SummaryItems.
//
// There is no guarantee for the order of the items in the slice.
// The order of the items is determined by the order of the tree traversal.
// The tree traversal is depth-first but based on a map, so the order is not
// guaranteed.
func (rs *RunSummary) Flatten() ([]*service.SummaryItem, error) {
	leaves := rs.pathTree.Flatten()

	summary := make([]*service.SummaryItem, 0, len(leaves))
	for _, leaf := range leaves {
		pathLen := len(leaf.Path)
		if pathLen == 0 {
			return nil, fmt.Errorf(
				"runsummary: empty path for item %v",
				leaf,
			)
		}

		value, err := json.Marshal(leaf.Value)
		if err != nil {
			return nil, fmt.Errorf(
				"runhistory: failed to marshal value for item %v: %v",
				leaf, err,
			)
		}

		if pathLen == 1 {
			summary = append(summary, &service.SummaryItem{
				Key:       leaf.Path[0],
				ValueJson: string(value),
			})
		} else {
			summary = append(summary, &service.SummaryItem{
				NestedKey: leaf.Path,
				ValueJson: string(value),
			})
		}
	}
	return summary, nil
}

// Clones the tree. This is useful for creating a snapshot of the tree.
func (rs *RunSummary) CloneTree() (pathtree.TreeData, error) {

	return rs.pathTree.CloneTree()
}

// Tree returns the tree data.
func (rs *RunSummary) Tree() pathtree.TreeData {

	return rs.pathTree.Tree()
}

// Serializes the object to send to the backend.
func (rs *RunSummary) Serialize() ([]byte, error) {
	return json.Marshal(rs.Tree())
}

// keyPath returns the key path for the given config item.
// If the item has a nested key, it returns the nested key.
// Otherwise, it returns a slice with the key.
func keyPath(item *service.SummaryItem) []string {
	if len(item.GetNestedKey()) > 0 {
		return item.GetNestedKey()
	}
	return []string{item.GetKey()}
}
