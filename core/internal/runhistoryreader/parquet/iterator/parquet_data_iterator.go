package iterator

import (
	"context"

	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

// ParquetDataIterator iterates over history steps in a run's parquet file.
type ParquetDataIterator struct {
	ctx             context.Context
	selectedRows    *SelectedRows
	selectedColumns *SelectedColumns

	recordReader pqarrow.RecordReader
	current      *RowGroupIterator
}

func NewParquetDataIterator(
	ctx context.Context,
	reader *pqarrow.FileReader,
	selectedRows *SelectedRows,
	selectedColumns *SelectedColumns,
) (RowIterator, error) {
	columnIndices := selectedColumns.GetColumnIndices()
	rowGroupIndices, err := selectedRows.GetRowGroupIndices()
	if err != nil {
		return nil, err
	}

	recordReader, err := reader.GetRecordReader(
		ctx,
		columnIndices,
		rowGroupIndices,
	)
	if err != nil {
		return nil, err
	}

	// No rows to read
	if !recordReader.Next() {
		return &NoopRowIterator{}, nil
	}

	current, err := NewRowGroupIterator(
		recordReader.RecordBatch(),
		selectedColumns,
		selectedRows,
	)
	if err != nil {
		return nil, err
	}

	return &ParquetDataIterator{
		ctx: ctx,

		selectedRows:    selectedRows,
		selectedColumns: selectedColumns,

		recordReader: recordReader,
		current:      current,
	}, nil
}

// Next implements RowIterator.Next.
func (r *ParquetDataIterator) Next() (bool, error) {
	for {
		next, err := r.current.Next()
		if next || err != nil {
			return next, err
		}

		if !r.recordReader.Next() {
			r.current.Release()
			return false, nil
		}

		r.current.Release()
		r.current, err = NewRowGroupIterator(
			r.recordReader.RecordBatch(),
			r.selectedColumns,
			r.selectedRows,
		)
		if err != nil {
			return false, err
		}
	}
}

// Value implements RowIterator.Value.
func (r *ParquetDataIterator) Value() KeyValueList {
	return r.current.Value()
}

// Release implements RowIterator.Release.
func (r *ParquetDataIterator) Release() {
	r.current.Release()
	r.recordReader.Release()
}
