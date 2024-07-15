package runsummary

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunSummary struct {
	pathTree *pathtree.PathTree
	stats    *Node
	mh       RunSummaryMetricHandler
}

type RunSummaryMetricHandler interface {
	// Hack to prevent an import cycle in the middle of a refactor.
	//
	// The RunSummary will soon be refactored.

	HackGetDefinedMetrics() map[string]*service.MetricRecord
	HackGetGlobMetrics() map[string]*service.MetricRecord
}

type Params struct {
	MetricHandler RunSummaryMetricHandler
}

func New(params Params) *RunSummary {
	rs := &RunSummary{
		pathTree: pathtree.New(),
		stats:    NewNode(),
		mh:       params.MetricHandler,
	}
	return rs
}

// GetSummaryTypes matches the path against the defined metrics and returns the
// requested summary type for the metric.
//
// It first checked the concrete metrics and then the glob metrics.
// The first match wins. If no match is found, it returns Latest.
func (rs *RunSummary) GetSummaryTypes(path []string) []SummaryType {
	if rs.mh == nil {
		return nil
	}

	// look for a matching rule
	// TODO: properly implement dot notation for nested keys,
	// see test_metric_full.py::test_metric_dotted for an example
	name := strings.Join(path, ".")

	types := make([]SummaryType, 0)

	for pattern, definedMetric := range rs.mh.HackGetDefinedMetrics() {
		if pattern == name {
			summary := definedMetric.GetSummary()
			if summary.GetNone() {
				return []SummaryType{None}
			}
			if summary.GetMax() {
				types = append(types, Max)
			}
			if summary.GetMin() {
				types = append(types, Min)
			}
			if summary.GetMean() {
				types = append(types, Mean)
			}
			if summary.GetLast() {
				types = append(types, Latest)
			}
		}
	}
	for pattern, globMetric := range rs.mh.HackGetGlobMetrics() {
		// match the key against the glob pattern:
		// note check for no error
		if match, err := filepath.Match(pattern, name); err == nil && match {
			summary := globMetric.GetSummary()
			if summary.GetNone() {
				return []SummaryType{None}
			}
			if summary.GetMax() {
				types = append(types, Max)
			}
			if summary.GetMin() {
				types = append(types, Min)
			}
			if summary.GetMean() {
				types = append(types, Mean)
			}
			if summary.GetLast() {
				types = append(types, Latest)
			}
		}
	}

	return types
}

// ApplyChangeRecord updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rs *RunSummary) ApplyChangeRecord(
	summaryRecord *service.SummaryRecord,
	onError func(error),
) {
	for _, item := range summaryRecord.GetUpdate() {
		var update interface{}
		// custom unmarshal function that handles NaN and +-Inf
		err := json.Unmarshal([]byte(item.GetValueJson()), &update)
		if err != nil {
			onError(err)
			continue
		}
		// update all the stats for the given key path
		path := keyPath(item)
		err = rs.stats.UpdateStats(path, update)
		if err != nil {
			onError(err)
			continue
		}
		// get the summary type for the item
		summaryTypes := rs.GetSummaryTypes(path)

		// skip if None in the summary type slice
		if len(summaryTypes) == 1 && summaryTypes[0] == None {
			continue
		}

		// get the requested stats for the item
		updateMap := make(map[string]interface{})
		for summaryType := range summaryTypes {
			update, err := rs.stats.GetStat(path, summaryTypes[summaryType])
			if err != nil {
				onError(err)
				continue
			}

			switch summaryTypes[summaryType] {
			case Max:
				updateMap["max"] = update
			case Min:
				updateMap["min"] = update
			case Mean:
				updateMap["mean"] = update
			case Latest:
				updateMap["last"] = update
			}
		}

		if len(updateMap) > 0 {
			// update summaryRecord with the new value
			jsonValue, err := json.Marshal(updateMap)
			if err != nil {
				onError(err)
				continue
			}
			item.ValueJson = string(jsonValue)

			// update the value to be stored in the tree
			update = updateMap
		}

		switch x := update.(type) {
		case map[string]any:
			rs.pathTree.SetSubtree(keyPath(item), x)
		default:
			rs.pathTree.Set(keyPath(item), x)
		}
	}

	for _, item := range summaryRecord.GetRemove() {
		rs.pathTree.Remove(keyPath(item))

		// remove the stats
		err := rs.stats.DeleteNode(keyPath(item))
		if err != nil {
			onError(err)
		}
	}
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

// CloneTree clones the tree. This is useful for creating a snapshot of the tree.
func (rs *RunSummary) CloneTree() map[string]any {
	return rs.pathTree.CloneTree()
}

// Get returns the summary value for a metric.
func (rs *RunSummary) Get(key string) (any, bool) {
	return rs.pathTree.GetLeaf(pathtree.TreePath{key})
}

// Serializes the object to send to the backend.
func (rs *RunSummary) Serialize() ([]byte, error) {
	return rs.pathTree.ToExtendedJSON()
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
