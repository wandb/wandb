package runhistory

import (
	"errors"
	"fmt"
	"strings"

	"github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/pkg/service"
)

// RunHistory is a set of metrics in a single step of a run.
//
// Keys for metrics logged using a nested dictionary, like
//
//	run.log({"a": {"b": 1}})
//
// get joined with ".", so that the above is equivalent to
//
//	run.log({"a.b": 1})
//
// The W&B UI supports nested metrics using "/"-separted keys,
// but this does not interact with dictionary nesting (much to
// the surprise of everyone).
type RunHistory struct {
	// metrics maps .-separated metric keys to values.
	//
	// Metric values are always one of:
	//  - int64
	//  - float64
	//  - string
	metrics map[string]any
}

func New() *RunHistory {
	return &RunHistory{metrics: make(map[string]any)}
}

// ToExtendedJSON returns the corresponding wandb-history.jsonl line.
//
// This serializes to an extension of JSON that supports +-Infinity
// and NaN numbers.
func (rh *RunHistory) ToExtendedJSON() ([]byte, error) {
	return json.Marshal(rh.metrics)
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

	for key, value := range rh.metrics {
		valueJSON, err := json.Marshal(value)

		if err != nil {
			errs = append(errs,
				fmt.Errorf("failed to marshal key %s: %v", key, err))
			continue
		}

		records = append(records, &service.HistoryItem{
			NestedKey: strings.Split(key, "."),
			ValueJson: string(valueJSON),
		})
	}

	return records, errors.Join(errs...)
}

// ForEach runs a callback on every metric according to its type.
//
// The callbacks must not modify the history. The callbacks return true
// to continue iteration, or false to stop early.
func (rh *RunHistory) ForEach(
	onInt func(key string, value int64) bool,
	onFloat func(key string, value float64) bool,
	onString func(key string, value string) bool,
) {
	for key, value := range rh.metrics {
		switch x := value.(type) {
		case int64:
			if !onInt(key, x) {
				return
			}

		case float64:
			if !onFloat(key, x) {
				return
			}

		case string:
			if !onString(key, x) {
				return
			}
		}
	}
}

// ForEachKey runs a callback on the key of each metric that has a value.
//
// Iteration stops if the callback returns false.
func (rh *RunHistory) ForEachKey(fn func(key string) bool) {
	for key := range rh.metrics {
		if !fn(key) {
			return
		}
	}
}

// Contains returns whether there is a value for the metric.
func (rh *RunHistory) Contains(key string) bool {
	_, exists := rh.metrics[key]
	return exists
}

// GetNumber returns the value of a number-valued metric.
//
// Integer-valued metrics are coerced to float64. Returns a boolean
// indicating whether there was a number-valued metric for the key.
func (rh *RunHistory) GetNumber(key string) (float64, bool) {
	value, exists := rh.metrics[key]
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

// GetString returns the value of a string-valued metric.
//
// Returns a boolean indicating whether there was a string-valued metric
// for the key.
func (rh *RunHistory) GetString(key string) (string, bool) {
	value, exists := rh.metrics[key]
	if !exists {
		return "", false
	}

	switch x := value.(type) {
	case string:
		return x, true
	default:
		return "", false
	}
}

// SetInt sets a metric to an integer value.
//
// See the [RunHistory] documentation about keys.
func (rh *RunHistory) SetInt(key string, value int64) {
	rh.metrics[key] = value
}

// SetFloat sets a metric to a float value.
//
// See the [RunHistory] documentation about keys.
func (rh *RunHistory) SetFloat(key string, value float64) {
	rh.metrics[key] = value
}

// SetString sets a metric to a string value.
//
// See the [RunHistory] documentation about keys.
func (rh *RunHistory) SetString(key string, value string) {
	rh.metrics[key] = value
}

// SetFromRecord records one or more metrics specified in a history proto.
//
// If the history item contains multiple metrics, such as if its ValueJson is
// a JSON-encoded dictionary, then metrics are set on a best-effort basis,
// and any errors are joined and returned.
func (rh *RunHistory) SetFromRecord(record *service.HistoryItem) error {
	var key string

	if len(record.NestedKey) > 0 {
		// See the documentation on Set for nested keys.
		key = strings.Join(record.NestedKey, ".")
	} else {
		key = record.Key
	}

	if key == "" {
		return errors.New("empty history item key")
	}

	// NOTE: ValueJson uses extended JSON; see documentation on ToEncodedJSON.
	var value any
	if err := json.Unmarshal([]byte(record.ValueJson), &value); err != nil {
		return fmt.Errorf("failed to unmarshal history item value: %v", err)
	}

	return rh.setFromUnmarshalledJSON(key, value)
}

// setFromUnmarshalledJSON sets metrics from a decoded JSON string.
//
// Given a JSON object with nested keys, field paths are concatenated
// using "." to create metric keys. So if key="k" and value={"a": {"b": 3}},
// then the metric "k.a.b" is set to 3.
func (rh *RunHistory) setFromUnmarshalledJSON(key string, value any) error {
	switch x := value.(type) {

	// encoding/json and segmentio-encoding/json decode all numbers as float64.
	case float64:
		rh.SetFloat(key, x)
		return nil

	case string:
		rh.SetString(key, x)
		return nil

	case map[string]any:
		var errs []error

		for subkey, value := range x {
			err := rh.setFromUnmarshalledJSON(key+"."+subkey, value)
			if err != nil {
				errs = append(errs, err)
			}
		}

		return errors.Join(errs...)

	default:
		return fmt.Errorf("unexpected type for history value: %T", x)
	}
}
