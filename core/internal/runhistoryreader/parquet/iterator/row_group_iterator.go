package iterator

import (
	"errors"
	"fmt"

	"github.com/apache/arrow-go/v18/arrow"
)

var ErrRowExceedsMaxValue = errors.New("row exceeds max value")

type keyIteratorPair struct {
	Key      string
	Iterator columnIterator
}

// RowGroupIterator iterates over a row group in a parquet file
type RowGroupIterator struct {
	recordBatch arrow.RecordBatch
	columns     map[string]keyIteratorPair
	cachedValue KeyValueList

	selectedRows    *SelectedRowsRange
	selectedColumns *SelectedColumns

	// hasValueFromLastScan indicates whether the iterator currently has a valid value
	// that should be checked before advancing
	hasValueFromLastScan bool
}

func NewRowGroupIterator(
	recordBatch arrow.RecordBatch,
	selectedColumns *SelectedColumns,
	selectedRows *SelectedRowsRange,
) (*RowGroupIterator, error) {
	// Increment the reference count of the record.
	recordBatch.Retain()

	wantedColumns := selectedColumns.GetRequestedColumns()
	wantedColumns[selectedRows.GetIndexKey()] = struct{}{}

	cols, err := mapToRecordColumns(
		recordBatch,
		selectedColumns.GetRequestedColumns(),
	)
	if err != nil {
		return nil, err
	}

	return &RowGroupIterator{
		recordBatch: recordBatch,
		columns:     cols,

		selectedRows:    selectedRows,
		selectedColumns: selectedColumns,
	}, nil
}

func mapToRecordColumns(
	recordBatch arrow.RecordBatch,
	requestedColumns map[string]struct{},
) (map[string]keyIteratorPair, error) {
	cols := make(
		map[string]keyIteratorPair,
		len(requestedColumns)+1,
	)

	for i := 0; i < int(recordBatch.NumCols()); i++ {
		colName := recordBatch.ColumnName(i)

		_, ok := requestedColumns[colName]
		if ok {
			it, err := newColumnIterator(recordBatch.Column(i))
			if err != nil {
				return nil, fmt.Errorf("%s > %v", colName, err)
			}
			cols[colName] = keyIteratorPair{
				Key:      colName,
				Iterator: it,
			}
		}
	}

	for colName := range requestedColumns {
		if _, ok := cols[colName]; !ok {
			return nil, fmt.Errorf(
				"column %s not found in record batch",
				colName,
			)
		}
	}

	return cols, nil
}

// Next implements RowIterator.Next.
//
// It advances the iterator to next row in the arrow.RecordBatch.
func (t *RowGroupIterator) Next() (bool, error) {
	// Clear the cached value for the row before advancing.
	t.cachedValue = nil

	// If we have a value from a previous scan iteration,
	// check if it's valid for the current scan range before advancing
	if t.hasValueFromLastScan {
		t.hasValueFromLastScan = false

		valid, err := t.checkRowValidity()
		if err != nil {
			return false, err
		}
		if valid {
			if t.checkRowHasAllColumns() {
				return true, nil
			}
		}
	}

	for {
		for _, c := range t.columns {
			if !c.Iterator.Next() {
				return false, nil
			}
		}

		validRow, err := t.checkRowValidity()
		if err != nil {
			return false, err
		}
		if !validRow {
			continue
		}

		hasAllColumns := t.checkRowHasAllColumns()
		if !hasAllColumns {
			continue
		}

		return true, nil
	}
}

// Value implements RowIterator.Value.
func (t *RowGroupIterator) Value() KeyValueList {
	// cache the value in case we're asked for it multiple times
	if t.cachedValue != nil {
		return t.cachedValue
	}

	t.cachedValue = make(KeyValueList, 0, len(t.selectedColumns.GetRequestedColumns()))
	for _, col := range t.columns {
		t.cachedValue = append(t.cachedValue, KeyValuePair{
			Key:   col.Key,
			Value: col.Iterator.Value(),
		})
	}
	return t.cachedValue
}

// Release implements RowIterator.Release.
func (t *RowGroupIterator) Release() {
	t.recordBatch.Release()
}

func (t *RowGroupIterator) checkRowValidity() (bool, error) {
	indexRow, ok := t.columns[t.selectedRows.indexKey]
	if !ok {
		return false, nil
	}

	if indexRow.Iterator == nil {
		return false, nil
	}
	indexRowValue := indexRow.Iterator.Value()

	if !t.selectedRows.IsRowGreaterThanMinValue(indexRowValue) {
		return false, nil
	}

	if !t.selectedRows.IsRowLessThanMaxValue(indexRowValue) {
		// Mark that we have a valid value for the next iteration
		t.hasValueFromLastScan = true
		return false, ErrRowExceedsMaxValue
	}

	return true, nil
}

func (t *RowGroupIterator) checkRowHasAllColumns() bool {
	if t.selectedColumns.selectAll {
		return true
	}
	for k := range t.selectedColumns.GetRequestedColumns() {
		if t.columns[k].Iterator.Value() == nil {
			return false
		}
	}
	return true
}
