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
	recordBatch arrow.RecordBatch,
	selectedColumns *SelectedColumns,
	selectedRows *SelectedRows,
) (RowIterator, error) {
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

	return &recordIterator{
		recordBatch:           recordBatch,
		columns:          cols,

		selectedRows: selectedRows,
		selectedColumns: selectedColumns,
	}, nil
}

func mapToRecordColumns(
	recordBatch arrow.RecordBatch,
	requestedColumns map[string]struct{},
) (map[string]keyIteratorPair, error) {
	cols := make(
		map[string]keyIteratorPair,
		len(requestedColumns) + 1,
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
