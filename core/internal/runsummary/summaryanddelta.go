package runsummary

// SummaryAndDelta is a run's full summary and, optionally, its changes since
// a chosen point, such as the last summary uploaded.
type SummaryAndDelta struct {
	full *RunSummary

	// delta is the changes since the last ResetDelta(true).
	//
	// It is nil if changes are not tracked.
	delta *Updates

	// deltaSinceFull is whether the last non-empty result of Serialize
	// was a delta.
	deltaSinceFull bool
}

// NewSummaryAndDelta returns an empty summary that doesn't track changes.
func NewSummaryAndDelta() *SummaryAndDelta {
	return &SummaryAndDelta{full: New()}
}

// Apply applies the updates to the full summary and adds them to the delta.
//
// A partial success is possible, in which case an error is returned.
func (s *SummaryAndDelta) Apply(updates *Updates) error {
	if s.delta != nil {
		s.delta.Merge(updates)
	}
	return updates.Apply(s.full)
}

// ResetDelta discards the delta and, if track is true, starts a new one.
//
// Does nothing given nil.
func (s *SummaryAndDelta) ResetDelta(track bool) {
	if s == nil {
		return
	}

	s.delta = nil
	if track {
		s.delta = NoUpdates()
	}
}

// DeltaSinceFull returns whether the last non-empty result of Serialize
// was a delta.
//
// Returns false given nil.
func (s *SummaryAndDelta) DeltaSinceFull() bool {
	return s != nil && s.deltaSinceFull
}

// Serialize returns the delta if preferDelta is true and the delta can be
// expressed, and the full summary otherwise.
//
// The delta can be expressed if changes are tracked and none of them is a
// removal. It leaves out values from run.log(). If it is empty, Serialize
// returns nil.
//
// The second return value is whether the result is a delta.
func (s *SummaryAndDelta) Serialize(preferDelta bool) ([]byte, bool, error) {
	asDelta := preferDelta && s.delta != nil && !s.delta.HasRemovals()

	serialize := s.full.Serialize
	if asDelta {
		serialize = s.delta.SerializeWithoutHistory
	}

	json, err := serialize()
	switch {
	case err != nil:
		return nil, false, err
	case asDelta && string(json) == "{}":
		return nil, false, nil
	}

	s.deltaSinceFull = asDelta
	return json, asDelta, nil
}
