package runsummary

import (
	"fmt"
	"path/filepath"

	// TODO: use simplejsonext for now until we replace the usage of json with
	// protocol buffer and proto json marshaler
	json "github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunSummary struct {
	pathTree *pathtree.PathTree
	stats    *Node
	mh       *runmetric.MetricHandler
}

type Params struct {
	MetricHandler *runmetric.MetricHandler
}

func New(params Params) *RunSummary {
	if params.MetricHandler == nil {
		params.MetricHandler = runmetric.NewMetricHandler()
	}

	rs := &RunSummary{
		pathTree: pathtree.New(),
		stats:    NewNode(),
		mh:       params.MetricHandler,
	}
	return rs
}

func statsTreeFromPathTree(tree pathtree.TreeData) *Node {
	stats := NewNode()
	for k, v := range tree {
		if subtree, ok := v.(pathtree.TreeData); ok {
			stats.nodes[k] = statsTreeFromPathTree(subtree)
		} else {
			stats.nodes[k] = &Node{
				leaf: &Leaf{
					Stats:   &Stats{},
					Summary: Latest,
				},
			}
		}
	}
	return stats
}

func NewFrom(tree pathtree.TreeData) *RunSummary {
	return &RunSummary{
		pathTree: pathtree.NewFrom(tree),
		stats:    statsTreeFromPathTree(tree),
		mh:       runmetric.NewMetricHandler(),
	}
}

// GetSummary matches the path against the defined metrics and returns the
// requested summary type for the metric.
//
// It first checked the concrete metrics and then the glob metrics.
// The first match wins. If no match is found, it returns Latest.
func (rs *RunSummary) GetSummary(path []string) (SummaryType, error) {
	// look for a matching rule
	// TODO: for now we only support top level keys.
	// For nested keys, we always return Latest.
	if len(path) != 1 {
		return Latest, nil
	}

	name := path[0]

	for pattern, definedMetric := range rs.mh.DefinedMetrics {
		// fmt.Printf("    kp: %v, pattern: %v\n", kp, pattern)
		if pattern == name {
			summary := definedMetric.GetSummary()
			fmt.Printf("    found defined metric. summary: %v\n", summary)
			if summary.GetMax() {
				fmt.Printf("+++    requested max summary for metric %v\n", name)
				return Max, nil
			}
			if summary.GetMin() {
				fmt.Printf("+++    requested min summary for metric %v\n", name)
				return Min, nil
			}
			if summary.GetMean() {
				fmt.Printf("+++    requested mean summary for metric %v\n", name)
				return Mean, nil
			}
			if summary.GetNone() {
				fmt.Printf("+++    requested none summary for metric %v\n", name)
				return None, nil
			}
			if summary.GetLast() {
				fmt.Printf("+++    requested last summary for metric %v\n", name)
				return Latest, nil
			}
		}
	}
	for pattern, globMetric := range rs.mh.GlobMetrics {
		// fmt.Printf("    kp: %v, pattern: %v\n", kp, pattern)
		// match the key against the glob pattern:
		if match, err := filepath.Match(pattern, name); err == nil {
			if match {
				summary := globMetric.GetSummary()
				fmt.Printf("    found glob metric. summary: %v\n", summary)
				if summary.GetMax() {
					fmt.Printf("---    requested max summary for metric %v\n", name)
					return Max, nil
				}
				if summary.GetMin() {
					fmt.Printf("---    requested min summary for metric %v\n", name)
					return Min, nil
				}
				if summary.GetMean() {
					fmt.Printf("---    requested mean summary for metric %v\n", name)
					return Mean, nil
				}
				if summary.GetNone() {
					fmt.Printf("---    requested none summary for metric %v\n", name)
					return None, nil
				}
				if summary.GetLast() {
					fmt.Printf("---    requested last summary for metric %v\n", name)
					return Latest, nil
				}
			}
		}
	}

	// if no match is found, return Latest
	fmt.Printf("+++    requested last summary for metric %v\n", name)
	return Latest, nil
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rs *RunSummary) ApplyChangeRecord(
	summaryRecord *service.SummaryRecord,
	onError func(error),
) {
	// handle updates
	updates := make([]*pathtree.PathItem, 0, len(summaryRecord.GetUpdate()))
	for _, item := range summaryRecord.GetUpdate() {
		fmt.Printf(">>> key: %v\n", item.GetKey())
		update, err := json.Unmarshal([]byte(item.GetValueJson()))
		if err != nil {
			onError(err)
			continue
		}
		// update all the stats for the given key path
		kp := keyPath(item)
		err = rs.stats.UpdateStats(kp, update)
		if err != nil {
			onError(err)
			continue
		}
		// get the summary type for the item
		fmt.Printf("      mh: %v\n", *rs.mh)
		fmt.Printf("      update: %v\n", update)

		st, err := rs.GetSummary(kp)
		if err != nil {
			onError(err)
			continue
		}

		// skip if requested summary type is None
		if st == None {
			continue
		}

		// get the requested stat for the item
		fmt.Printf("+++    requested stat for metric %v: %v\n", kp, st)
		update, err = rs.stats.GetStat(kp, st)
		fmt.Printf("      update: %v\n", update)
		if err != nil {
			onError(err)
			continue
		}

		// store the update
		updates = append(updates, &pathtree.PathItem{
			Path:  keyPath(item),
			Value: update,
		})

		// update summaryRecord with the new value
		jsonValue, err := json.Marshal(update)
		if err != nil {
			onError(err)
			continue
		}
		item.ValueJson = string(jsonValue)
	}
	rs.pathTree.ApplyUpdate(updates, onError)

	// handle removes
	removes := make([]*pathtree.PathItem, 0, len(summaryRecord.GetRemove()))
	for _, item := range summaryRecord.GetRemove() {
		removes = append(removes, &pathtree.PathItem{
			Path: keyPath(item),
		})
		// remove the stats
		err := rs.stats.DeleteNode(keyPath(item))
		if err != nil {
			onError(err)
		}
	}
	rs.pathTree.ApplyRemove(removes)

	// TODO: rm this debug
	// for k, v := range rs.stats.nodes {
	// 	if v.leaf != nil {
	// 		fmt.Printf("runsummary: stats node %v stats: %v\n", k, v.leaf.Stats)
	// 	}
	// }
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
