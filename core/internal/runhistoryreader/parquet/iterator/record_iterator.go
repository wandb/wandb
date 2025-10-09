package iterator

import (
	"fmt"

	"github.com/apache/arrow-go/v18/arrow"
)

type keyIteratorPair struct {
	Key      string
	Iterator columnIterator
}

// recordIterator iterates over a row group in a parquet file
type recordIterator struct {
	recordBatch           arrow.RecordBatch
	columns          map[string]keyIteratorPair
	cachedValue            KeyValueList

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
			it, err := newColumnIterator(record.Column(i))
			if err != nil {
				return nil, fmt.Errorf("%s > %v", colName, err)
			}
			cols[colName] = keyIteratorPair{
				Key:      colName,
				Iterator: it,
			}
		}
	}

	t := &recordIterator{
		recordBatch:           record,
		columns:          cols,

		selectedRows: selectedRows,
		selectedColumns: selectedColumns,
	}
	return t, nil
}

// Next implements RowIterator.Next.
//
// It advances the iterator to next row in the arrow.RecordBatch.
func (t *recordIterator) Next() (bool, error) {
	// Clear the cached value for the row before advancing.
	t.cachedValue = nil

RowSearch:
	for {
		for _, c := range t.columns {
			if !c.Iterator.Next() {
				return false, nil
			}
		}

		if !t.selectedRows.IsRowValid(t.columns) {
			continue
		}

		// Only return the row if it has all the selected columns
		if !t.selectedColumns.selectAll {
			for k := range t.selectedColumns.GetRequestedColumns() {
				if t.columns[k].Iterator.Value() == nil {
					continue RowSearch
				}
			}
		}

		return true, nil
	}
}

// Value implements RowIterator.Value.
func (t *recordIterator) Value() KeyValueList {
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
func (t *recordIterator) Release() {
	t.recordBatch.Release()
}
