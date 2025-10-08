package iterator

import (
	"context"

	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

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

func NewRowIterator(
	ctx context.Context,
	reader *pqarrow.FileReader,
	selectedRows *SelectedRows,
	selectedColumns *SelectedColumns,
) (RowIterator, error) {
	// For empty parquet files, return a noop iterator.
	if reader.ParquetReader().NumRows() <= 0 {
		return &NoopRowIterator{}, nil
	}

	return NewParquetDataIterator(
		ctx,
		reader,
		selectedRows,
		selectedColumns,
	)
}
