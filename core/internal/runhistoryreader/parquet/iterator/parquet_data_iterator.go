package iterator

import (
	"context"
	"math"

	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

// ParquetDataIterator uses recordIterators
// to iterate over arrow.RecordBatches in the given parquet file
//
// It is the high level iterator used to iterate
// over a run history parquet file.
type ParquetDataIterator struct {
	ctx    context.Context
	reader *pqarrow.FileReader
	keys   []string
	config IteratorConfig

	selectAllRows   bool
	rowGroupIndices []int

	recordReader pqarrow.RecordReader
	current      RowIterator
}

func NewRowIterator(
	ctx context.Context,
	reader *pqarrow.FileReader,
	keys []string,
	config IteratorConfig,
) (*ParquetDataIterator, error) {
	// Check if this file is empty
	if reader.ParquetReader().NumRows() == 0 {
		rgi := &ParquetDataIterator{
			current: &NoopRowIterator{},
		}
		return rgi, nil
	}

	if reader.Props.BatchSize <= 0 {
		if len(keys) > 0 {
			reader.Props.BatchSize = int64(batchSizeForSchemaSize(len(keys)))
		} else {
			numColumns := reader.ParquetReader().MetaData().Schema.NumColumns()
			reader.Props.BatchSize = int64(batchSizeForSchemaSize(numColumns))
		}
	}

	var selectedRowGroups SeletedRowGroups
	if config.selectAllRows {
		selectedRowGroups = SelectAllRowGroups(reader)
	} else {
		var err error
		selectedRowGroups, err = SelectOnlyRowGroups(reader, config)
		if err != nil {
			return nil, err
		}
	}

	var selectedColumns SelectedColumns
	parquetSchema := reader.ParquetReader().MetaData().Schema
	if len(keys) > 0 {
		// include the index key as we need to read it to filter rows
		selectedKeys := keys
		selectedKeys = append(selectedKeys, config.key)
		var err error
		selectedColumns, err = SelectOnlyColumns(selectedKeys, parquetSchema)
		if err != nil {
			return nil, err
		}
	} else {
		selectedColumns = SelectAllColumns(parquetSchema)
	}

	recordReader, err := reader.GetRecordReader(
		ctx,
		selectedColumns.GetColumnIndices(),
		selectedRowGroups.GetRowGroupIndices(),
	)
	if err != nil {
		return nil, err
	}

	rgi := &ParquetDataIterator{
		ctx:    ctx,
		reader: reader,
		keys:   keys,
		config: config,

		selectAllRows:   config.selectAllRows,
		rowGroupIndices: selectedRowGroups.GetRowGroupIndices(),

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

	if r.recordReader != nil && r.recordReader.Next() {
		opts := []RecordIteratorOption{
			RecordIteratorWithResultCols(r.keys),
		}
		if !r.selectAllRows {
			opts = append(opts, RecordIteratorWithPage(r.config))
		}
		r.current.Release()
		r.current, err = NewRecordIterator(
			r.recordReader.RecordBatch(),
			opts...,
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
	if r.recordReader != nil {
		r.recordReader.Release()
	}
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
