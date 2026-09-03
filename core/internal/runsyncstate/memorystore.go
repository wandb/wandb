package runsyncstate

type memoryStore struct {
	startState            StartState
	startStateInitialized bool
}

// GetOrInitStartState implements Store.GetOrInitStartState.
func (s *memoryStore) GetOrInitStartState(
	initialState StartState,
) (StartState, error) {
	if !s.startStateInitialized {
		s.startState = initialState
		s.startStateInitialized = true
	}

	return s.startState, nil
}
