package iterator

import (
	"context"
	"math"

	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

const (
	StepKey      = "_step"
	TimestampKey = "_timestamp"
)

// KeyValuePair is the name and value of a single metric in a history row.
type KeyValuePair struct {
	Key   string
	Value any
}

// KeyValueList is a list of KeyValuePairs which represent a single history row.
type KeyValueList []KeyValuePair

// RowIterator iterates over history rows (a.k.a. steps)
// that are stored in a parquet file.
type RowIterator interface {
	// Next advances the iterator to the next value.
	Next() (bool, error)
	// Value returns the current value of the iterator.
	Value() KeyValueList
	// Release releases the resources used by the iterator.
	// It must be called exactly once after the iterator is no longer needed.
	Release()
}

// NewRowIterator returns an iterator over all rows in the given parquet file.
// If the parquet file is empty, a noop iterator is returned.
//
// reader is safe to use after the creation of the iterator.
func NewRowIterator(
	ctx context.Context,
	reader *pqarrow.FileReader,
	selectedRows *SelectedRowsRange,
	selectedColumns *SelectedColumns,
) (*ParquetDataIterator, error) {
	// For empty parquet files, return a noop iterator.
	if reader.ParquetReader().NumRows() <= 0 {
		return nil, nil
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
	// When reading data from a parquet file,
	// The reader reserves an amount of memory for N rows.
	// This is more efficient since the allocations are batched
	// and the values are contiguous (less work for gc).
	//
	// But, the size of a row is determined by the number (and type) of columns.
	// So we use a very unscientific formula. Some example breakpoints:
	// At <=100 columns, reserve 10k rows (max reservation)
	// At 1k columns, reserve 1k rows
	// At >=10k columns, reserve 100 rows
	if numColumns < 1 {
		return 10000
	}

	return int(math.Max(math.Min(10000, float64(1000000/numColumns)), 100))
}
