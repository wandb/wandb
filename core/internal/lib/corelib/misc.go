package corelib

func NilIfZero[T comparable](x T) *T {
	var zero T
	if x == zero {
		return nil
	}
	return &x
}
