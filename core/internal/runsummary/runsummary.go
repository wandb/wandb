package runsummary

import (
	"errors"
	"fmt"

	"github.com/wandb/simplejsonext"
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

// SetFromRecord explicitly sets the summary value of a metric.
//
// Returns an error if the item is not valid.
func (rs *RunSummary) SetFromRecord(record *spb.SummaryItem) error {
	value, err := simplejsonext.UnmarshalString(record.ValueJson)
	if err != nil {
		return fmt.Errorf("runsummary: invalid summary JSON: %v", err)
	}

	rs.getOrMakeSummary(keyPath(record)).SetExplicit(value)

	return nil
}

func (rs *RunSummary) RemoveFromRecord(record *spb.SummaryItem) {
	if len(record.NestedKey) > 0 {
		rs.Remove(
			pathtree.PathOf(
				record.NestedKey[0],
				record.NestedKey[1:]...,
			))
	} else {
		rs.Remove(pathtree.PathOf(record.Key))
	}
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

type summaryOrHistoryItem interface {
	GetNestedKey() []string
	GetKey() string
}

// keyPath returns the key on the summary or history proto as a path.
func keyPath[T summaryOrHistoryItem](item T) pathtree.TreePath {
	if len(item.GetNestedKey()) > 0 {
		return pathtree.PathOf(
			item.GetNestedKey()[0],
			item.GetNestedKey()[1:]...,
		)
	}
	return pathtree.PathOf(item.GetKey())
}
