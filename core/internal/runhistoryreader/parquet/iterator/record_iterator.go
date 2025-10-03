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
	columns          []keyIteratorPair
	resultCols       []keyIteratorPair
	resultsWhitelist map[string]struct{}

	requireAllValues bool
	indexKey         string
	indexCol         columnIterator
	validIndex       func(columnIterator) bool
	value            KeyValueList
}

type RecordIteratorOption func(*recordIterator)

func (r *recordIterator) Apply(opts ...RecordIteratorOption) {
	for _, opt := range opts {
		opt(r)
	}
}

func RecordIteratorWithPage(config IteratorConfig) RecordIteratorOption {
	return func(t *recordIterator) {
		t.indexKey = config.key
		t.validIndex = func(it columnIterator) bool {
			if it == nil {
				return false
			}
			// cache the type of Value()
			switch it.Value().(type) {
			case int64:
				minStep := int64(config.min)
				maxStep := int64(config.max)
				t.validIndex = func(it columnIterator) bool {
					step, ok := it.Value().(int64)
					if !ok {
						return false
					}
					return step >= minStep && step < maxStep
				}
			case float64:
				t.validIndex = func(it columnIterator) bool {
					indexVal, ok := it.Value().(float64)
					if !ok {
						return false
					}

					return indexVal >= config.min && indexVal < config.max
				}
			default:
				t.validIndex = func(columnIterator) bool {
					return false
				}
			}
			return t.validIndex(it)
		}
	}
}

func RecordIteratorWithResultCols(columns []string) RecordIteratorOption {
	whitelist := map[string]struct{}{}
	for _, c := range columns {
		whitelist[c] = struct{}{}
	}
	return func(t *recordIterator) {
		if len(columns) == 0 {
			return
		}

		t.resultsWhitelist = whitelist
	}
}

func NewRecordIterator(record arrow.RecordBatch, options ...RecordIteratorOption) (RowIterator, error) {
	record.Retain()
	t := &recordIterator{
		record:           record,
		resultsWhitelist: nil,
		columns:          make([]keyIteratorPair, int(record.NumCols())),
		validIndex: func(columnIterator) bool {
			return true
		},
		indexKey: StepKey,
	}
	t.Apply(options...)

	for i := 0; i < int(record.NumCols()); i++ {
		colName := record.ColumnName(i)
		col := record.Column(i)
		it, err := newColumnIterator(col, columnIteratorConfig{returnRawBinary: false})
		if err != nil {
			return nil, fmt.Errorf("%s > %w", colName, err)
		}
		t.columns[i] = keyIteratorPair{
			Key:      colName,
			Iterator: it,
		}

		if t.indexKey == colName {
			t.indexCol = it
		}
	}

	t.resultCols = t.columns
	if t.resultsWhitelist != nil {
		resultCols := []keyIteratorPair{}
		for _, c := range t.resultCols {
			if _, whitelisted := t.resultsWhitelist[c.Key]; whitelisted {
				resultCols = append(resultCols, c)
			}
		}
		t.resultCols = resultCols
		t.requireAllValues = true
	}

	return t, nil
}

// Next implements the RowIterator interface.
// Next advances the iterator to next column in the arrow.RecordBatch.
func (t *recordIterator) Next() (bool, error) {
	t.value = nil
	for {
		for _, c := range t.columns {
			if !c.Iterator.Next() {
				return false, nil
			}
		}

		if !t.validIndex(t.indexCol) {
			continue
		}

		if t.requireAllValues {
			allValues := true
			for _, c := range t.resultCols {
				if c.Iterator.Value() == nil {
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
	t.value = make(KeyValueList, len(t.resultCols))
	for i, col := range t.resultCols {
		t.value[i] = KeyValuePair{
			Key:   col.Key,
			Value: col.Iterator.Value(),
		}
	}
	return t.value
}

// Release implements the RowIterator interface.
// Release frees the memory used to read the current arrow.RecordBatch.
// Release should be called only once after the iterator is no longer needed.
// Additional calls to Release are no-ops.
func (t *recordIterator) Release() {
	t.record.Release()
}
