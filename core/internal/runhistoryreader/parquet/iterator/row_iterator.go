package iterator

import (
	"context"
	"math"

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

	if reader.Props.BatchSize <= 0 {
		reader.Props.BatchSize = int64(
			batchSizeForSchemaSize(len(selectedColumns.GetRequestedColumns())),
		)
	}

	return NewParquetDataIterator(
		ctx,
		reader,
		selectedRows,
		selectedColumns,
	)
}

func batchSizeForSchemaSize(numColumns int) int {
	// builder.Reserve reserves an amount of memory for N rows, which is more efficient since the
	// allocations are batched and the values are contiguous (less work for gc).
	// But remember that how big a row is is determined by the number (and type) of columns. So we
	// use a very unscientific formula. Some example breakpoints:
	// At <=100 columns, reserve 10k rows (max reservation)
	// At 1k columns, reserve 1k rows
	// At >=10k columns, reserve 100 rows
	if numColumns < 1 {
		return 10000
	}

	return int(math.Max(math.Min(10000, float64(1000000/numColumns)), 100))
}
