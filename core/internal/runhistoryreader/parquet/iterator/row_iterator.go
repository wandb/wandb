package iterator

import "math"

// This file copies most of its logic from how history parquet files
// are read on the backend.
// See: https://github.com/wandb/core/blob/master/services/gorilla/internal/parquet/row_iterator.go

const (
	StepKey      = "_step"
	TimestampKey = "_timestamp"
)

// KeyValuePair is a key-value pair mapping,
// it represents a single metric for a history row.
// Where Key is the metric name and Value is the metric value.
type KeyValuePair struct {
	Key   string
	Value any
}

// KeyValueList is a list of KeyValuePairs which represent a single history row.
type KeyValueList []KeyValuePair

// RowIterator is an interface to iterate over history rows
// for a runs history parquet file.
type RowIterator interface {
	// Next advances the iterator to the next value.
	Next() (bool, error)
	// Value returns the current value of the iterator.
	Value() KeyValueList
	// Release releases the resources used by the iterator.
	Release()
}

// IteratorConfig is a configuration for which history rows should be selected.
//
// key is the key to filter on.
// min is the minimum value to filter on it is inclusive.
// max is the maximum value to filter on it is exclusive.
// selectAllRows will not filter any rows
// based on the index key when set to true.
type IteratorConfig struct {
	key           string
	min           float64
	max           float64
	selectAllRows bool
}

func NewRowFilteredIteratorConfig(
	indexKey string,
	minValue float64,
	maxValue float64,
) IteratorConfig {
	return IteratorConfig{
		key:           indexKey,
		min:           minValue,
		max:           maxValue,
		selectAllRows: false,
	}
}

func NewSelectAllRowsIteratorConfig(indexKey string) IteratorConfig {
	return IteratorConfig{
		key:           indexKey,
		min:           0,
		max:           math.MaxFloat64,
		selectAllRows: true,
	}
}
