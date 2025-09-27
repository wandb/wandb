package iterator

// NoopRowIterator is a row iterator that always returns false
// when attempting to advance to the next row.
// Its value is always an empty KeyValueList.
type NoopRowIterator struct{}

func (d *NoopRowIterator) Next() (bool, error) { return false, nil }

func (d *NoopRowIterator) Value() KeyValueList { return KeyValueList{} }

func (d *NoopRowIterator) Release() {}
