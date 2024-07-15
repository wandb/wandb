package runhistory

import (
	"errors"
	"fmt"
	"slices"

	"github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

// RunHistory is a set of metrics in a single step of a run.
//
// Metric values are always one of:
//   - bool
//   - int64
//   - float64
//   - string
type RunHistory struct {
	metrics *pathtree.PathTree
}

func New() *RunHistory {
	return &RunHistory{metrics: pathtree.New()}
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
func (rh *RunHistory) ToRecords() ([]*service.HistoryItem, error) {
	var records []*service.HistoryItem
	var errs []error

	rh.metrics.ForEachLeaf(func(path pathtree.TreePath, value any) bool {
		valueJSON, err := json.Marshal(value)

		if err != nil {
			errs = append(errs,
				fmt.Errorf("failed to marshal key %v: %v", path, err))
			return true
		}

		records = append(records, &service.HistoryItem{
			NestedKey: path,
			ValueJson: string(valueJSON),
		})

		return true
	})

	return records, errors.Join(errs...)
}

// ForEach runs a callback on every metric according to its type.
//
// The callbacks must not modify the history. The callbacks return true
// to continue iteration, or false to stop early.
func (rh *RunHistory) ForEach(
	onBool func(path pathtree.TreePath, value bool) bool,
	onInt func(path pathtree.TreePath, value int64) bool,
	onFloat func(path pathtree.TreePath, value float64) bool,
	onString func(path pathtree.TreePath, value string) bool,
) {
	rh.metrics.ForEachLeaf(func(path pathtree.TreePath, value any) bool {
		switch x := value.(type) {
		case bool:
			return onBool(path, x)

		case int64:
			return onInt(path, x)

		case float64:
			return onFloat(path, x)

		case string:
			return onString(path, x)
		}

		return true
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

// IsEmpty returns true if no metrics are logged.
func (rh *RunHistory) IsEmpty() bool {
	return rh.metrics.IsEmpty()
}

// Contains returns whether there is a value for the metric.
func (rh *RunHistory) Contains(path ...string) bool {
	// TODO: should this work for non-leaf values?
	_, exists := rh.metrics.GetLeaf(path)
	return exists
}

// SetBool sets a metric to a boolean value.
func (rh *RunHistory) SetBool(path pathtree.TreePath, value bool) {
	rh.metrics.Set(path, value)
}

// SetInt sets a metric to an integer value.
func (rh *RunHistory) SetInt(path pathtree.TreePath, value int64) {
	rh.metrics.Set(path, value)
}

// SetFloat sets a metric to a float value.
func (rh *RunHistory) SetFloat(path pathtree.TreePath, value float64) {
	rh.metrics.Set(path, value)
}

// SetString sets a metric to a string value.
func (rh *RunHistory) SetString(path pathtree.TreePath, value string) {
	rh.metrics.Set(path, value)
}

// SetFromRecord records one or more metrics specified in a history proto.
//
// If the history item contains multiple metrics, such as if its ValueJson is
// a JSON-encoded dictionary, then metrics are set on a best-effort basis,
// and any errors are joined and returned.
func (rh *RunHistory) SetFromRecord(record *service.HistoryItem) error {
	var pathAppendSafe pathtree.TreePath

	if len(record.NestedKey) > 0 {
		// We clone the nested key so that it's safe to append to it
		// without further cloning.
		pathAppendSafe = slices.Clone(record.NestedKey)
	} else if len(record.Key) > 0 {
		pathAppendSafe = pathtree.TreePath{record.Key}
	} else {
		return errors.New("empty history item key")
	}

	// NOTE: ValueJson uses extended JSON; see documentation on ToEncodedJSON.
	var value any
	if err := json.Unmarshal([]byte(record.ValueJson), &value); err != nil {
		return fmt.Errorf("failed to unmarshal history item value: %v", err)
	}

	return rh.setFromUnmarshalledJSON(pathAppendSafe, value)
}

// setFromUnmarshalledJSON sets metrics from a decoded JSON string.
func (rh *RunHistory) setFromUnmarshalledJSON(
	pathAppendSafe pathtree.TreePath,
	value any,
) error {
	switch x := value.(type) {

	case bool:
		rh.SetBool(pathAppendSafe, x)
		return nil

	// encoding/json and segmentio-encoding/json decode all numbers as float64.
	case float64:
		rh.SetFloat(pathAppendSafe, x)
		return nil

	case string:
		rh.SetString(pathAppendSafe, x)
		return nil

	case map[string]any:
		var errs []error

		for subkey, value := range x {
			subpath := pathAppendSafe
			subpath = append(subpath, subkey)

			err := rh.setFromUnmarshalledJSON(subpath, value)
			if err != nil {
				errs = append(errs, err)
			}
		}

		return errors.Join(errs...)

	default:
		return fmt.Errorf("unexpected type for history value: %T", x)
	}
}
