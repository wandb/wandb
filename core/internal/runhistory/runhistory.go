package runhistory

import (
	"errors"
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/pathtree"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunHistory is a set of metrics in a single step of a run.
type RunHistory struct {
	metrics *pathtree.PathTree[any]
}

func New() *RunHistory {
	return &RunHistory{metrics: pathtree.New[any]()}
}

// ToExtendedJSON returns the corresponding wandb-history.jsonl line.
//
// This serializes to an extension of JSON that supports +-Infinity
// and NaN numbers.
func (rh *RunHistory) ToExtendedJSON() ([]byte, error) {
	return rh.metrics.ToExtendedJSON()
}

// ToRecords returns the history as a slice of records.
//
// Metrics that cannot be marshalled to JSON are skipped without affecting
// other metrics.
//
// TODO: Don't convert history back to protos. Delete this method.
func (rh *RunHistory) ToRecords() ([]*spb.HistoryItem, error) {
	var records []*spb.HistoryItem
	var errs []error

	rh.metrics.ForEachLeaf(func(path pathtree.TreePath, value any) bool {
		valueJSON, err := simplejsonext.Marshal(value)

		if err != nil {
			errs = append(errs,
				fmt.Errorf("failed to marshal key %v: %v", path, err))
			return true
		}

		records = append(records, &spb.HistoryItem{
			NestedKey: path.Labels(),
			ValueJson: string(valueJSON),
		})

		return true
	})

	return records, errors.Join(errs...)
}

// ForEachNumber runs a callback on every numeric metric.
//
// All numbers are converted to float64, which may lose precision.
//
// The callbacks must not modify the history. The callbacks return true
// to continue iteration, or false to stop early.
func (rh *RunHistory) ForEachNumber(
	fn func(path pathtree.TreePath, value float64) bool,
) {
	rh.metrics.ForEachLeaf(func(path pathtree.TreePath, value any) bool {
		switch x := value.(type) {

		// Numeric metrics are always float64 or int64 because all our JSON
		// libraries decode numbers as float64/int64 and because the only
		// allowed setters are for float64/int64.
		case float64:
			return fn(path, x)
		case int64:
			return fn(path, float64(x))

		default:
			return true
		}
	})
}

// ForEachKey runs a callback on the key of each metric that has a value.
//
// Iteration stops if the callback returns false.
func (rh *RunHistory) ForEachKey(fn func(path pathtree.TreePath) bool) {
	rh.metrics.ForEachLeaf(func(path pathtree.TreePath, value any) bool {
		return fn(path)
	})
}

// ForEach runs a callback on each metric that has a value.
//
// Iteration stops if a callback returns false. Nil callbacks are ignored.
func (rh *RunHistory) ForEach(
	onFloat func(path pathtree.TreePath, value float64) bool,
	onInt func(path pathtree.TreePath, value int64) bool,
	onOther func(path pathtree.TreePath, value any) bool,
) {
	rh.metrics.ForEachLeaf(func(path pathtree.TreePath, value any) bool {
		switch x := value.(type) {
		case float64:
			if onFloat != nil {
				return onFloat(path, x)
			}
		case int64:
			if onInt != nil {
				return onInt(path, x)
			}
		default:
			if onOther != nil {
				return onOther(path, x)
			}
		}

		return true
	})
}

// IsEmpty returns true if no metrics are logged.
func (rh *RunHistory) IsEmpty() bool {
	return rh.metrics.IsEmpty()
}

// Contains returns whether there is a value for the metric.
func (rh *RunHistory) Contains(path pathtree.TreePath) bool {
	// TODO: should this work for non-leaf values?
	_, exists := rh.metrics.GetLeaf(path)
	return exists
}

// GetNumber returns the value of a number-valued metric.
func (rh *RunHistory) GetNumber(path pathtree.TreePath) (float64, bool) {
	value, exists := rh.metrics.GetLeaf(path)
	if !exists {
		return 0, false
	}

	switch x := value.(type) {
	case int64:
		return float64(x), true
	case float64:
		return x, true
	default:
		return 0, false
	}
}

// SetFloat sets the value of a float-valued metric.
func (rh *RunHistory) SetFloat(path pathtree.TreePath, value float64) {
	rh.metrics.Set(path, value)
}

// SetInt sets the value of an int-valued metric.
func (rh *RunHistory) SetInt(path pathtree.TreePath, value int64) {
	rh.metrics.Set(path, value)
}

// SetString sets the value of a string-valued metric.
func (rh *RunHistory) SetString(path pathtree.TreePath, value string) {
	rh.metrics.Set(path, value)
}

// SetFromRecord records one or more metrics specified in a history proto.
//
// If the history item contains multiple metrics, such as if its ValueJson is
// a JSON-encoded dictionary, then metrics are set on a best-effort basis,
// and any errors are joined and returned.
func (rh *RunHistory) SetFromRecord(record *spb.HistoryItem) error {
	var path pathtree.TreePath

	switch {
	case len(record.NestedKey) > 0:
		path = pathtree.PathOf(record.NestedKey[0], record.NestedKey[1:]...)
	case len(record.Key) > 0:
		path = pathtree.PathOf(record.Key)
	default:
		return errors.New("empty history item key")
	}

	value, err := simplejsonext.UnmarshalString(record.ValueJson)
	if err != nil {
		return fmt.Errorf("failed to unmarshal history item value: %v", err)
	}

	rh.setFromUnmarshalledJSON(path, value)
	return nil
}

// setFromUnmarshalledJSON sets metrics from a decoded JSON string.
func (rh *RunHistory) setFromUnmarshalledJSON(
	path pathtree.TreePath,
	value any,
) {
	switch x := value.(type) {
	// Recurse for maps to maintain their tree structure.
	case map[string]any:
		for subkey, value := range x {
			rh.setFromUnmarshalledJSON(path.With(subkey), value)
		}

	default:
		rh.metrics.Set(path, x)
	}
}
