package sentry

// Option represents an optional configuration value.
//
// The zero value is unset. Use Set to distinguish an explicitly configured
// zero value, such as false, 0, or "", from an unset option.
type Option[T any] struct {
	Value T
	IsSet bool
}

// Set returns an Option containing v.
func Set[T any](v T) Option[T] {
	return Option[T]{Value: v, IsSet: true}
}

// Or returns the option value when set, or defaultValue otherwise.
func (o Option[T]) Or(defaultValue T) T {
	if o.IsSet {
		return o.Value
	}
	return defaultValue
}
