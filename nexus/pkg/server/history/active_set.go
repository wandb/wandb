package history

type Value interface {
	GetKey() string
	GetNestedKey() []string
	GetValueJson() string
}

type ActiveSet[T Value] struct {
	values map[string]T
	idx    int64
	f      func(idx int64, values map[string]T)
}

func NewActiveSet[T Value](idx int64, f func(idx int64, values map[string]T)) *ActiveSet[T] {
	return &ActiveSet[T]{
		values: make(map[string]T),
		idx:    idx,
		f:      f,
	}
}

func (as *ActiveSet[T]) GetIdx() int64 {
	return as.idx
}

func (as *ActiveSet[T]) Update(key string, value T) {
	as.values[key] = value
}

func (as *ActiveSet[T]) Updates(values ...T) {
	for _, value := range values {
		as.values[value.GetKey()] = value
	}
}

func (as *ActiveSet[T]) Get(key string) (T, bool) {
	if value, ok := as.values[key]; ok {
		return value, ok
	}
	var value T
	return value, false
}

func (as *ActiveSet[T]) Gets() []T {
	var values []T
	for _, value := range as.values {
		values = append(values, value)
	}
	return values
}

func (as *ActiveSet[T]) GetValue(key string) (string, bool) {
	if value, ok := as.values[key]; ok {
		return value.GetValueJson(), ok
	}
	return "", false
}

func (as *ActiveSet[T]) Flush() {
	as.FlushWithIdx(as.idx + 1)
}

func (as *ActiveSet[T]) FlushWithIdx(idx int64) {
	if as.f != nil {
		as.f(as.idx, as.values)
	}
	as.idx = idx
	clear(as.values)
}
