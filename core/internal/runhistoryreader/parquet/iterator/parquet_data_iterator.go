package iterator

import (
	"context"

	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

// ParquetDataIterator iterates over history steps in a run's parquet file.
type ParquetDataIterator struct {
	ctx             context.Context
	selectedRows    *SelectedRowsRange
	selectedColumns *SelectedColumns
	fileReader      *pqarrow.FileReader

	recordReader pqarrow.RecordReader
	current      *RowGroupIterator

	// lastStep is the last step value that has been read from the parquet file.
	lastStep int64
}

func NewParquetDataIterator(
	ctx context.Context,
	reader *pqarrow.FileReader,
	selectedRows *SelectedRowsRange,
	selectedColumns *SelectedColumns,
) (*ParquetDataIterator, error) {
	pqDataIterator := &ParquetDataIterator{
		ctx:             ctx,
		selectedRows:    selectedRows,
		selectedColumns: selectedColumns,
		fileReader:      reader,
		lastStep:        0,
	}
	err := pqDataIterator.createNewRecordReader()
	if err != nil {
		return nil, err
	}
	return pqDataIterator, nil
}

func (r *ParquetDataIterator) GetSelectedRows() *SelectedRowsRange {
	return r.selectedRows
}

// UpdateQueryRange updates the range of rows
// that should be read from the parquet file.
//
// When the minValue is less than the r.lastStep,
// a new row group iterator is created.
//
// If an error occurs, the iterator is no longer valid and should be released.
func (r *ParquetDataIterator) UpdateQueryRange(
	minValue float64,
	maxValue float64,
) error {
	if r.current == nil && int64(minValue) >= r.lastStep {
		return nil
	}

	// Update the selected range
	r.selectedRows = SelectRowsInRange(
		r.fileReader,
		StepKey,
		minValue,
		maxValue,
	)

	// When we want data from minValue we need to create a new record reader
	// since the Arrow RecordReader doesn't support backward seeking
	// after data has been consumed.
	if int64(minValue) < r.lastStep {
		return r.createNewRecordReader()
	}
	r.current.selectedRows = r.selectedRows

	return nil
}

// Next implements RowIterator.Next.
func (r *ParquetDataIterator) Next() (bool, error) {
	// If there's no current iterator (e.g., empty file), return false
	if r.current == nil {
		return false, nil
	}

	for {
		next, err := r.current.Next()
		if next || err != nil {
			r.lastStep++
			return next, err
		}

		if !r.recordReader.Next() {
			r.current.Release()
			r.current = nil

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
	if r.current == nil {
		return nil
	}
	return r.current.Value()
}

// Release implements RowIterator.Release.
func (r *ParquetDataIterator) Release() {
	if r.current != nil {
		r.current.Release()
	}
	if r.recordReader != nil {
		r.recordReader.Release()
	}
}

// createNewRecordReader creates a fresh RecordReader when going backwards or restarting.
// This adds latency but is necessary since the Arrow RecordReader doesn't
// support backward seeking after data has been consumed.
func (r *ParquetDataIterator) createNewRecordReader() error {
	// Release the old resources
	r.Release()

	// Create a new record reader for the updated range
	columnIndices := r.selectedColumns.GetColumnIndices()
	rowGroupIndices, err := r.selectedRows.GetRowGroupIndices()
	if err != nil {
		return err
	}

	recordReader, err := r.fileReader.GetRecordReader(
		r.ctx,
		columnIndices,
		rowGroupIndices,
	)
	if err != nil {
		return err
	}
	r.recordReader = recordReader

	// No rows to read
	if !r.recordReader.Next() {
		r.current = nil
		return nil
	}

	// Get the record batch after calling Next()
	recordBatch := r.recordReader.RecordBatch()

	// Create new row group iterator with the batch
	current, err := NewRowGroupIterator(
		recordBatch,
		r.selectedColumns,
		r.selectedRows,
	)
	if err != nil {
		return err
	}

	r.current = current
	r.lastStep = 0
	return nil
}
