package parquet

const (
	StepKey      = "_step"
	TimestampKey = "_timestamp"
)

// KeyValuePair is the name and value of a single metric in a history row.
type KeyValuePair struct {
	Key   string
	Value any
}

// KeyValueList is a list of KeyValuePairs which represent a single history row.
type KeyValueList []KeyValuePair

// StepValue returns the _step value for this row, or 0 if not found.
func (kvl KeyValueList) StepValue() int64 {
	for _, kv := range kvl {
		if kv.Key == StepKey {
			switch v := kv.Value.(type) {
			case int64:
				return v
			case uint64:
				return int64(v)
			case float64:
				return int64(v)
			}
		}
	}
	return 0
}
