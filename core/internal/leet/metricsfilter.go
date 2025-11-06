package leet

// FilterState tracks the filter state (for run overview or metric charts).
type FilterState struct {
	active  bool   // filter input mode: whether the user is typing
	draft   string // what the user is typing
	applied string // committed pattern
}
