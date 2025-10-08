package iterator

import (
	"context"

	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

// ParquetDataIterator uses recordIterators
// to iterate over arrow.RecordBatches in the given parquet file
//
// It is the high level iterator used to iterate
// over a run history parquet file.
type ParquetDataIterator struct {
	ctx             context.Context
	selectedRows    *SelectedRows
	selectedColumns *SelectedColumns

	recordReader pqarrow.RecordReader
	current      RowIterator
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

	rgi := &ParquetDataIterator{
		ctx: ctx,

		selectedRows:    selectedRows,
		selectedColumns: selectedColumns,

		recordReader: recordReader,
		current:      &NoopRowIterator{},
	}

	return rgi, nil
}

func (r *ParquetDataIterator) Next() (bool, error) {
	next, err := r.current.Next()
	if next || err != nil {
		return next, err
	}

	if r.recordReader.Next() {
		r.current.Release()
		r.current, err = NewRecordIterator(
			r.recordReader.RecordBatch(),
			r.selectedColumns,
			r.selectedRows,
		)
		if err != nil {
			return false, err
		}
		return r.Next()
	}

	r.current.Release()
	r.current = &NoopRowIterator{}
	return false, nil
}

func (r *ParquetDataIterator) Value() KeyValueList {
	return r.current.Value()
}

// Release implements the RowIterator interface.
// Releases the underlying resources used by the iterator.
// It should be called only once after the iterator is no longer needed.
// Additional calls to Release are no-ops.
func (r *ParquetDataIterator) Release() {
	r.current.Release()
	r.recordReader.Release()
}
