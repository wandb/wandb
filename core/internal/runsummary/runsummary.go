package runsummary

import (
	"errors"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunSummary tracks summary statistics for all metrics in a run.
type RunSummary struct {
	// summaries maps metrics to metricSummary objects.
	summaries *pathtree.PathTree[*metricSummary]
}

func New() *RunSummary {
	return &RunSummary{summaries: pathtree.New[*metricSummary]()}
}

// Set sets the explicit summary value for a metric.
func (rs *RunSummary) Set(path pathtree.TreePath, value any) {
	rs.getOrMakeSummary(path).SetExplicit(value)
}

// Remove deletes the summary for a metric.
func (rs *RunSummary) Remove(path pathtree.TreePath) {
	summary, ok := rs.summaries.GetLeaf(path)
	if !ok {
		return
	}

	summary.Clear()
}

// UpdateSummaries updates metric summaries based on their new values
// and returns the updates made.
//
// The list of updates may be non-empty even on error. An error state
// may leave the run summary partially updated.
func (rs *RunSummary) UpdateSummaries(
	history *runhistory.RunHistory,
) ([]*spb.SummaryItem, error) {
	var updates []*spb.SummaryItem
	var errs []error

	history.ForEach(
		func(path pathtree.TreePath, value float64) bool {
			update, err := rs.updateSummary(path, func(ms *metricSummary) {
				ms.UpdateFloat(value)
			})

			if err != nil {
				errs = append(errs, err)
			}
			if update != nil {
				updates = append(updates, update)
			}

			return true
		},
		func(path pathtree.TreePath, value int64) bool {
			update, err := rs.updateSummary(path, func(ms *metricSummary) {
				ms.UpdateInt(value)
			})

			if err != nil {
				errs = append(errs, err)
			}
			if update != nil {
				updates = append(updates, update)
			}

			return true
		},
		func(path pathtree.TreePath, value any) bool {
			update, err := rs.updateSummary(path, func(ms *metricSummary) {
				ms.UpdateOther(value)
			})

			if err != nil {
				errs = append(errs, err)
			}
			if update != nil {
				updates = append(updates, update)
			}

			return true
		},
	)

	return updates, errors.Join(errs...)
}

func (rs *RunSummary) updateSummary(
	path pathtree.TreePath,
	update func(*metricSummary),
) (*spb.SummaryItem, error) {
	summary := rs.getOrMakeSummary(path)

	update(summary)
	json, err := summary.ToExtendedJSON()

	switch {
	case err != nil:
		return nil, err

	case json != "":
		return &spb.SummaryItem{
			NestedKey: path.Labels(),
			ValueJson: json,
		}, nil

	default:
		return nil, nil
	}
}

// ConfigureMetric sets the values to track for a metric.
func (rs *RunSummary) ConfigureMetric(
	path pathtree.TreePath,
	noSummary bool,
	track SummaryTypeFlags,
) {
	summary := rs.getOrMakeSummary(path)
	summary.noSummary = noSummary
	summary.track = track
}

// ToRecords returns this summary as a list of SummaryItem protos.
//
// It may return a non-empty list even on error, in which case some
// values may be missing.
func (rs *RunSummary) ToRecords() ([]*spb.SummaryItem, error) {
	var records []*spb.SummaryItem
	var errs []error

	rs.summaries.ForEachLeaf(
		func(path pathtree.TreePath, summary *metricSummary) bool {
			encoded, err := summary.ToExtendedJSON()

			if err != nil {
				errs = append(errs, err)
				return true
			}
			if len(encoded) == 0 {
				return true
			}

			item := &spb.SummaryItem{ValueJson: encoded}
			if path.Len() == 1 {
				item.Key = path.End()
			} else {
				item.NestedKey = path.Labels()
			}
			records = append(records, item)

			return true
		})

	return records, errors.Join(errs...)
}

func (rs *RunSummary) toSummaryTree() *pathtree.PathTree[any] {
	jsonTree := pathtree.New[any]()

	rs.summaries.ForEachLeaf(
		func(path pathtree.TreePath, summary *metricSummary) bool {
			if jsonSummary := summary.ToMarshallableValue(); jsonSummary != nil {
				jsonTree.Set(path, jsonSummary)
			}

			return true
		})

	return jsonTree
}

// ToNestedMaps returns a nested-map representation of the summary.
//
// All values are JSON-marshallable types.
func (rs *RunSummary) ToNestedMaps() map[string]any {
	return rs.toSummaryTree().CloneTree()
}

// Serializes the object to send to the backend.
func (rs *RunSummary) Serialize() ([]byte, error) {
	return rs.toSummaryTree().ToExtendedJSON()
}

func (rs *RunSummary) getOrMakeSummary(path pathtree.TreePath) *metricSummary {
	return rs.summaries.GetOrMakeLeaf(
		path,
		func() *metricSummary { return &metricSummary{} },
	)
}
