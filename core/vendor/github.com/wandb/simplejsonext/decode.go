package simplejsonext

// Unmarshal decodes a JSON representation from b as a generic value:
// int64, float64, string, bool, nil, []any, or map[string]any.
func Unmarshal(b []byte) (any, error) {
	p := NewParserFromSlice(b)
	val, err := p.Parse()
	if err != nil {
		return nil, err
	}
	return val, p.CheckEmpty()
}

func UnmarshalObject(b []byte) (map[string]any, error) {
	p := NewParserFromSlice(b)
	val, err := p.ParseObject()
	if err != nil {
		return nil, err
	}
	return val, p.CheckEmpty()
}

// UnmarshalString decodes a JSON representation from b as a generic
// value: int64, float64, string, bool, nil, []any, or map[string]any.
func UnmarshalString(s string) (any, error) {
	p := NewParserFromString(s)
	val, err := p.Parse()
	if err != nil {
		return nil, err
	}
	return val, p.CheckEmpty()
}

func UnmarshalObjectString(s string) (map[string]any, error) {
	p := NewParserFromString(s)
	val, err := p.ParseObject()
	if err != nil {
		return nil, err
	}
	return val, p.CheckEmpty()
}
