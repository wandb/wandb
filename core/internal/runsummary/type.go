package runsummary

type SummaryTypeFlags uint64

const (
	Unset  SummaryTypeFlags = 0
	Latest                  = 1 << (iota - 1)
	Min
	Max
	Mean
)

func (f SummaryTypeFlags) IsEmpty() bool {
	return f == 0
}

func (f SummaryTypeFlags) HasAny(flag SummaryTypeFlags) bool {
	return (f & flag) > 0
}
