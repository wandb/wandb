package runsummary

type SummaryTypeFlags uint64

const (
	Unset  SummaryTypeFlags = 0
	Latest                  = 1 << (iota - 1)
	Min
	Max
	Mean

	// BestMaximize is like Max, but is stored in the "best" key.
	BestMaximize

	// BestMinimize is like Min, but is stored in the "best" key.
	//
	// If both BestMaximize and BestMinimize are set,
	// BestMaximize takes precedence.
	BestMinimize
)

func (f SummaryTypeFlags) IsEmpty() bool {
	return f == 0
}

func (f SummaryTypeFlags) HasAny(flag SummaryTypeFlags) bool {
	return (f & flag) > 0
}
