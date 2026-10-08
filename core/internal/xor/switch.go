package xor

import "errors"

var (
	ErrNoMatch          = errors.New("no match")
	ErrMoreThanOneMatch = errors.New("more than one match")
)

// Switch begins a new "exclusive" switch statement.
//
// In an exclusive switch statement, exactly one case must match.
// Implementing this normally requires some duplication:
//
//	if !exactlyOneMatch(cond1, cond2, cond3) {
//		// error
//	}
//
//	switch {
//	case cond1: ...
//	case cond2: ...
//	case cond3: ...
//	}
//
// To add one condition, you must update two places. And the `exactlyOneMatch`
// helper function needs to be defined, as it does not exist in Go's standard
// library.
//
// This structure allows rewriting the above like so:
//
//	ran, err := xor.Switch().
//		Case(cond1, ...).
//		Case(cond2, ...).
//		Case(cond3, ...).
//		RunExactlyOne()
func Switch() *SwitchDSL {
	return &SwitchDSL{}
}

type SwitchDSL struct {
	cases []switchCase
}

type switchCase struct {
	Condition bool
	Function  func() error
}

// Case declares a case of the switch.
//
// This returns the switch and is intended to be chained:
//
//	ran, err := xor.Switch().
//		Case(cond1, func() error { ... }).
//		Case(cond2, func() error { ... }).
//		RunExactlyOne()
//
// If the cases are large, using a variable instead of chaining
// can be more readable because it has less indentation:
//
//	cases := xor.Switch()
//	cases.Case(cond1, func() error {
//		...
//	})
//	cases.Case(cond2, func() error {
//		...
//	})
//	ran, err := cases.RunExactlyOne()
//
// In the above, the return value can be ignored.
func (s *SwitchDSL) Case(cond bool, fn func() error) *SwitchDSL {
	s.cases = append(s.cases, switchCase{cond, fn})
	return s
}

// RunExactlyOne runs the switch statement, expecting exactly one case to match.
//
// If exactly one case matches, returns true and its result.
// Otherwise, returns false and either ErrNoMatch or ErrMoreThanOneMatch.
//
// The `ran` return value allows distinguishing between a case that returned
// ErrNoMatch / ErrMoreThanOneMatch and a switch statement that didn't execute.
func (s *SwitchDSL) RunExactlyOne() (ran bool, err error) {
	var selected switchCase

	for _, sc := range s.cases {
		if !sc.Condition {
			continue
		}

		if selected.Condition {
			return false, ErrMoreThanOneMatch
		}

		selected = sc
	}

	if selected.Condition {
		return true, selected.Function()
	} else {
		return false, ErrNoMatch
	}
}
