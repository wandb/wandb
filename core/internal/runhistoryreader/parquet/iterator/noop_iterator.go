package iterator

// NoopRowIterator is a row iterator that always returns false
// when attempting to advance to the next row.
//
// Its value is always an empty KeyValueList.
type NoopRowIterator struct{}

// Next implements RowIterator.Next.
func (d *NoopRowIterator) Next() (bool, error) { return false, nil }

// Value implements RowIterator.Value.
func (d *NoopRowIterator) Value() KeyValueList { return KeyValueList{} }

// Release implements RowIterator.Release.
func (d *NoopRowIterator) Release() {}
