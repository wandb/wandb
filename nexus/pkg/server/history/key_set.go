package history

type KeySetOption[T any] func(*KeySet[T])

type KeySet[T any] struct {
	values map[string]*T
	merge  func(value, newValue *T)
	match  func(pattern, key string) (bool, error)
}

func NewKeySet[T any](opts ...KeySetOption[T]) *KeySet[T] {
	ks := &KeySet[T]{
		values: make(map[string]*T),
	}
	for _, opt := range opts {
		opt(ks)
	}
	return ks
}

func WithMatch[T any](match func(pattern, key string) (bool, error)) KeySetOption[T] {
	return func(ks *KeySet[T]) {
		ks.match = match
	}
}

func WithMerge[T any](merge func(value, newValue *T)) KeySetOption[T] {
	return func(ks *KeySet[T]) {
		ks.merge = merge
	}
}

func (ks *KeySet[T]) Replace(key string, value *T) {
	ks.values[key] = value
}

func (ks *KeySet[T]) Merge(key string, value *T) {
	if dst, ok := ks.Get(key); ok {
		ks.merge(dst, value)
	} else {
		ks.Replace(key, value)
	}
}

func (ks *KeySet[T]) Get(key string) (*T, bool) {
	if ks.values == nil || key == "" {
		return nil, false
	}
	if value, ok := ks.values[key]; ok {
		return value, ok
	}
	return nil, false
}

func (ks *KeySet[T]) Match(key string) (*T, bool) {
	if ks.values == nil || key == "" {
		return nil, false
	}
	for pattern, value := range ks.values {
		if match, err := ks.match(pattern, key); err != nil {
			// h.logger.CaptureError("error matching metric", err)
			continue
		} else if match {
			return value, true
		}
	}
	return nil, false
}

func (ks *KeySet[T]) GetValues() map[string]*T {
	return ks.values
}
