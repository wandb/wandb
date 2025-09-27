package iterator

// multiIterator handles reading rows from multiple run history partitions.
// A parition referes to a single parquet file export of a run's history.
type multiIterator struct {
	iterators []RowIterator
	offset    int
}

func NewMultiIterator(iterators []RowIterator) RowIterator {
	return &multiIterator{
		iterators: iterators,
	}
}

func (m *multiIterator) Next() (bool, error) {
	if next, err := m.iterators[m.offset].Next(); next || err != nil {
		return next, err
	}
	m.offset++
	if m.offset >= len(m.iterators) {
		return false, nil
	}
	return m.Next()
}

func (m *multiIterator) Value() KeyValueList {
	return m.iterators[m.offset].Value()
}

func (m *multiIterator) Release() {
	for _, it := range m.iterators {
		it.Release()
	}
}

func (m *multiIterator) Iterators() []RowIterator {
	return m.iterators
}
