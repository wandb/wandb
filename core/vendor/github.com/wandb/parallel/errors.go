package parallel

import (
	"strings"
)

// MultiError is used internally to wrap multiple errors that occur
// within a function
type MultiError interface {
	error
	Unwrap() []error
	One() error
}

type multiError struct {
	errors []error
}

func (e *multiError) Error() string {
	return strings.Join(e.errorStrings(), "\n")
}

func (e *multiError) Unwrap() []error {
	return e.errors
}

func (e *multiError) errorStrings() (strings []string) {
	for _, err := range e.errors {
		if err != nil {
			strings = append(strings, err.Error())
		}
	}
	return
}

func (e *multiError) One() error {
	return e.errors[0]
}

func NewMultiError(errs ...error) MultiError {
	if len(errs) > 0 {
		return &multiError{errors: errs} // concrete type not exposed
	}
	return nil
}

// Combine multiple errors into one MultiError, discarding all nil errors and
// flattening any existing MultiErrors. If the result has no errors, the result
// is nil.
func CombineErrors(errs ...error) MultiError {
	var combined []error
	for _, err := range errs {
		if err == nil {
			continue
		}
		switch typedErr := err.(type) {
		case MultiError:
			combined = append(combined, typedErr.Unwrap()...)
		default:
			combined = append(combined, err)
		}
	}
	return NewMultiError(combined...)
}
