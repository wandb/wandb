package iterator

import (
	"fmt"

	"github.com/apache/arrow-go/v18/arrow"
)

type keyIteratorPair struct {
	Key      string
	Iterator columnIterator
}

// recordIterator iterates over columnIterators
// to read columns in the given arrow.RecordBatch in chunks.
type recordIterator struct {
	record           arrow.RecordBatch
	columns          map[string]keyIteratorPair
	value            KeyValueList

	selectedRows *SelectedRows
	selectedColumns *SelectedColumns
}

func NewRecordIterator(
	record arrow.RecordBatch,
	selectedColumns *SelectedColumns,
	selectedRows *SelectedRows,
) (RowIterator, error) {
	// Increment the reference count of the record.
	record.Retain()

	cols := make(
		map[string]keyIteratorPair,
		len(selectedColumns.GetRequestedColumns()) + 1,
	)
	wantedColumns := selectedColumns.GetRequestedColumns()
	for i := 0; i < int(record.NumCols()); i++ {
		colName := record.ColumnName(i)
		_, ok := wantedColumns[colName]
		if ok || colName == selectedColumns.GetIndexKey() {
			it, err := newColumnIterator(
				record.Column(i),
				columnIteratorConfig{returnRawBinary: false},
			)
			if err != nil {
				return nil, fmt.Errorf("%s > %w", colName, err)
			}
			cols[colName] = keyIteratorPair{
				Key:      colName,
				Iterator: it,
			}
		}
	}

	t := &recordIterator{
		record:           record,
		columns:          cols,

		selectedRows: selectedRows,
		selectedColumns: selectedColumns,
	}
	return t, nil
}

// Next implements the RowIterator interface.
// Next advances the iterator to next column in the arrow.RecordBatch.
func (t *recordIterator) Next() (bool, error) {
	t.value = nil
	for {
		for _, c := range t.columns {
			next := c.Iterator.Next()
			if !next {
				return false, nil
			}
		}

		if !t.selectedRows.IsRowValid(t.columns) {
			continue
		}

		// Only return the row if it has all the selected columns
		if !t.selectedColumns.selectAll {
			allValues := true
			for k := range t.selectedColumns.GetRequestedColumns() {
				if t.columns[k].Iterator.Value() == nil {
					allValues = false
				}
			}
			if !allValues {
				continue
			}
		}

		return true, nil
	}
}

// Value implements the RowIterator interface.
// Value returns a KeyValueList of the current row in the arrow.RecordBatch.
func (t *recordIterator) Value() KeyValueList {
	if t.value != nil { // cache the value in case we're asked for it multiple times
		return t.value
	}
	t.value = make(KeyValueList, len(t.selectedColumns.GetRequestedColumns()))
	i := 0
	for col := range t.selectedColumns.GetRequestedColumns() {
		col := t.columns[col]
		t.value[i] = KeyValuePair{
			Key:   col.Key,
			Value: col.Iterator.Value(),
		}
		i++
	}
	return t.value
}

// Release implements the RowIterator interface.
//
// Release decrements the reference count of the record.
// When the reference count goes to zero, the memory is freed.
// Release should be called only once after the iterator is no longer needed.
func (t *recordIterator) Release() {
	t.record.Release()
}
