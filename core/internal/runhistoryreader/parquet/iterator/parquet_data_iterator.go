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
	fileReader      *pqarrow.FileReader

	recordReader pqarrow.RecordReader
	current      RowIterator

	lastStep int64
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
		fileReader:      reader,

		recordReader: recordReader,
		current:      current,
		lastStep:     0,
	}, nil
}

func (r *ParquetDataIterator) UpdateQueryRange(
	minValue float64,
	maxValue float64,
	selectAll bool,
) error {

	// Update the selected range
	r.selectedRows.minValue = minValue
	r.selectedRows.maxValue = maxValue
	r.selectedRows.selectAll = selectAll

	// When we want data from minValue we need to create a new record reader
	// since the Arrow RecordReader doesn't support backward seeking
	// after data has been consumed.
	if int64(minValue) < r.lastStep {
		return r.createNewRecordReader()
	}

	return nil
}

// Next implements RowIterator.Next.
func (r *ParquetDataIterator) Next() (bool, error) {
	for {
		next, err := r.current.Next()
		if next || err != nil {
			r.lastStep++
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

// createNewRecordReader creates a fresh RecordReader when going backwards or restarting.
// This adds latency but is necessary since the Arrow RecordReader doesn't
// support backward seeking after data has been consumed.
func (r *ParquetDataIterator) createNewRecordReader() error {
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
		r.current = &NoopRowIterator{}
		r.lastStep = 0
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
