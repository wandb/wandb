package api

import (
	"fmt"
)

// RetryError is returned from a client initialized using this package
// when a request retry fails.
//
// It contains information about the error that was being retried,
// allowing the caller to construct better error messages.
type RetryError struct {
	Inner      error
	LastStatus string
}

func (err *RetryError) Error() string {
	return fmt.Sprintf(
		"%s\nwhile retrying: %s",
		err.Inner.Error(), err.LastStatus)
}

func (err *RetryError) Unwrap() error {
	return err.Inner
}
