package nullify

func NilIfZero[T comparable](x T) *T {
	var zero T
	if x == zero {
		return nil
	}
	return &x
}

func ZeroIfNil[T comparable](x *T) T {
	if x == nil {
		// zero value of T
		var zero T
		return zero
	}
	return *x
}
