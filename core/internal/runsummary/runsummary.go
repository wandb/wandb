package runsummary

import (
	"errors"
	"fmt"
	"strings"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/pkg/service"
)

// RunSummary tracks summary statistics for all metrics in a run.
type RunSummary struct {
	// summaries maps .-separated metric names to their summaries.
	summaries map[string]*metricSummary
}

func New() *RunSummary {
	return &RunSummary{summaries: make(map[string]*metricSummary)}
}

// SetFromRecord explicitly sets the summary value of a metric.
//
// Returns an error if the item is not valid.
func (rs *RunSummary) SetFromRecord(record *service.SummaryItem) error {
	value, err := simplejsonext.UnmarshalString(record.ValueJson)
	if err != nil {
		return fmt.Errorf("runsummary: invalid summary JSON: %v", err)
	}

	summary, ok := rs.summaries[keyPath(record)]
	if !ok {
		summary = &metricSummary{}
		rs.summaries[keyPath(record)] = summary
	}
	summary.SetExplicit(value)

	return nil
}

// Remove deletes the summary for a metric.
func (rs *RunSummary) Remove(key string) {
	summary, ok := rs.summaries[key]
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
) ([]*service.SummaryItem, error) {
	var updates []*service.SummaryItem
	var errs []error

	history.ForEach(
		func(path pathtree.TreePath, value float64) bool {
			update, err := rs.updateSummaryFloat(path, value)

			if err != nil {
				errs = append(errs, err)
			}
			if update != nil {
				updates = append(updates, update)
			}

			return true
		},
		func(path pathtree.TreePath, value int64) bool {
			update, err := rs.updateSummaryInt(path, value)

			if err != nil {
				errs = append(errs, err)
			}
			if update != nil {
				updates = append(updates, update)
			}

			return true
		},
		func(path pathtree.TreePath, value any) bool {
			update, err := rs.updateSummaryOther(path, value)

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

func (rs *RunSummary) updateSummaryFloat(
	path pathtree.TreePath,
	value float64,
) (*service.SummaryItem, error) {
	return rs.updateSummary(path, func(ms *metricSummary) {
		ms.UpdateFloat(value)
	})
}

func (rs *RunSummary) updateSummaryInt(
	path pathtree.TreePath,
	value int64,
) (*service.SummaryItem, error) {
	return rs.updateSummary(path, func(ms *metricSummary) {
		ms.UpdateInt(value)
	})
}

func (rs *RunSummary) updateSummaryOther(
	path pathtree.TreePath,
	value any,
) (*service.SummaryItem, error) {
	return rs.updateSummary(path, func(ms *metricSummary) {
		ms.UpdateOther(value)
	})
}

func (rs *RunSummary) updateSummary(
	path pathtree.TreePath,
	update func(*metricSummary),
) (*service.SummaryItem, error) {
	key := strings.Join(path.Labels(), ".")
	summary := rs.getOrMakeSummary(key)

	update(summary)
	json, err := summary.ToExtendedJSON()

	switch {
	case err != nil:
		return nil, err

	case json != "":
		return &service.SummaryItem{
			Key:       key,
			ValueJson: json,
		}, nil

	default:
		return nil, nil
	}
}

// ConfigureMetric sets the values to track for a metric.
func (rs *RunSummary) ConfigureMetric(
	key string,
	noSummary bool,
	track SummaryTypeFlags,
) {
	summary := rs.getOrMakeSummary(key)
	summary.noSummary = noSummary
	summary.track = track
}

// ToRecords returns this summary as a list of SummaryItem protos.
//
// It may return a non-empty list even on error, in which case some
// values may be missing.
func (rs *RunSummary) ToRecords() ([]*service.SummaryItem, error) {
	var records []*service.SummaryItem
	var errs []error

	for key, summary := range rs.summaries {
		encoded, err := summary.ToExtendedJSON()

		if err != nil {
			errs = append(errs, err)
			continue
		}
		if len(encoded) == 0 {
			continue
		}

		records = append(records,
			&service.SummaryItem{
				Key:       key,
				ValueJson: encoded,
			})
	}

	return records, errors.Join(errs...)
}

// ToMap returns the summary as a map from .-separated keys to values.
//
// Values are JSON-marshallable types.
func (rs *RunSummary) ToMap() map[string]any {
	m := make(map[string]any)

	for key, summary := range rs.summaries {
		value := summary.ToMarshallableValue()

		if value != nil {
			m[key] = value
		}
	}

	return m
}

// Serializes the object to send to the backend.
func (rs *RunSummary) Serialize() ([]byte, error) {
	jsonTree := pathtree.New()

	for key, summary := range rs.summaries {
		if len(key) == 0 {
			continue
		}

		labels := strings.Split(key, ".")
		path := pathtree.PathOf(labels[0], labels[1:]...)

		if jsonSummary := summary.ToMarshallableValue(); jsonSummary != nil {
			jsonTree.Set(path, jsonSummary)
		}
	}

	return jsonTree.ToExtendedJSON()
}

func (rs *RunSummary) getOrMakeSummary(key string) *metricSummary {
	summary, ok := rs.summaries[key]
	if !ok {
		summary = &metricSummary{}
		rs.summaries[key] = summary
	}

	return summary
}

type summaryOrHistoryItem interface {
	GetNestedKey() []string
	GetKey() string
}

// keyPath returns the key on the summary or history proto as a path.
func keyPath[T summaryOrHistoryItem](item T) string {
	if len(item.GetNestedKey()) > 0 {
		return strings.Join(item.GetNestedKey(), ".")
	}
	return item.GetKey()
}
