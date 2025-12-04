package iterator

// multiIterator iterates over multiple RowIterators in sequence.
type multiIterator struct {
	iterators []*ParquetDataIterator
	offset    int
}

func NewMultiIterator(iterators []*ParquetDataIterator) RowIterator {
	return &multiIterator{
		iterators: iterators,
	}
}

// Next implements the RowIterator.Next.
func (m *multiIterator) Next() (bool, error) {
	for m.offset < len(m.iterators) {
		next, err := m.iterators[m.offset].Next()
		if next || err != nil {
			return next, err
		}
		m.offset++
	}
	return false, nil
}

// Value implements the RowIterator.Value.
func (m *multiIterator) Value() KeyValueList {
	return m.iterators[m.offset].Value()
}

// Release implements the RowIterator.Release.
func (m *multiIterator) Release() {
	for _, it := range m.iterators {
		it.Release()
	}
}

func (m *multiIterator) Iterators() []*ParquetDataIterator {
	return m.iterators
}
