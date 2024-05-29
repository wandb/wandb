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
	return &RunSummary{
		pathTree: pathtree.New(),
	}
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
	// fmt.Println("++ApplyChangeRecord")
	// fmt.Println(summaryRecord)
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
	rs.ApplyUpdate(updates, onError)

	removes := make([]*pathtree.PathItem, 0, len(summaryRecord.GetRemove()))
	for _, item := range summaryRecord.GetRemove() {
		removes = append(removes, &pathtree.PathItem{
			Path: keyPath(item),
		})
	}
	rs.pathTree.ApplyRemove(removes)
}

// ApplyUpdate updates values in the summary tree.
func (rs *RunSummary) ApplyUpdate(
	items []*pathtree.PathItem,
	onError func(error),
) {
	for _, item := range items {
		if err := updateAtPath(rs.pathTree.Tree(), item.Path, item.Value); err != nil {
			onError(err)
			continue
		}
	}
}

func updateAtPath(
	tree pathtree.TreeData,
	path []string,
	value interface{},
) error {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree, err := pathtree.GetOrMakeSubtree(tree, pathPrefix)

	if err != nil {
		return err
	}

	_, ok := subtree[key]
	if !ok {
		// If the key doesn't exist, create a new item.
		switch value.(type) {
		case float32, float64, int32, int64, int:
			subtree[key] = NewItem[float64]()
		default:
			subtree[key] = value
		}
	}
	if v, ok := subtree[key]; ok {
		// fmt.Println("++updateAtPath")
		// fmt.Println(v, value)
		switch t := value.(type) {
		case float32:
			Update(v.(*Item[float64]), float64(t))
		case float64:
			Update(v.(*Item[float64]), t)
		case int32:
			Update(v.(*Item[float64]), float64(t))
		case int64:
			Update(v.(*Item[float64]), float64(t))
		case int:
			Update(v.(*Item[float64]), float64(t))
		default:
			subtree[key] = value
		}
	} else {
		subtree[key] = value
	}

	return nil
}

// Flatten the summary tree into a slice of SummaryItems.
//
// There is no guarantee for the order of the items in the slice.
// The order of the items is determined by the order of the tree traversal.
// The tree traversal is depth-first but based on a map, so the order is not
// guaranteed.
func (rs *RunSummary) Flatten(
	definedMetrics map[string]*service.MetricRecord,
) ([]*service.SummaryItem, error) {
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
		fmt.Println("\n\n++Flatten")
		fmt.Println(definedMetrics)
		fmt.Println(leaf.Path, leaf.Value)

		var val interface{}
		if pathLen == 1 {
			switch leaf.Value.(type) {
			case *Item[float64]:
				// TODO: get aggregation type from definedMetrics
				val = leaf.Value.(*Item[float64]).Latest
			default:
				fmt.Println("NONONONO")
				val = leaf.Value
			}
		} else {
			val = leaf.Value
		}

		value, err := json.Marshal(val)
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
	fmt.Println(summary)
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
	// TODO: this is wrong

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
