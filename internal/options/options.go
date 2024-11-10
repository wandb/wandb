package options

// Option is a generic interface for applying configuration options
type Option interface {
	Apply(v interface{})
}

// OptionFunc is a function type that implements the Option interface
type OptionFunc func(v interface{})

// Apply implements the Option interface for OptionFunc
func (fn OptionFunc) Apply(v interface{}) {
	fn(v)
}

// NewOptionFunc creates a new Option from a function
func NewOptionFunc(fn func(v interface{})) Option {
	return OptionFunc(fn)
}
