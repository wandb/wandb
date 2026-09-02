package runsyncstate

type memoryStore struct {
	startingStep            int64
	startingStepInitialized bool
}

// GetOrInitStartingStep implements Store.GetOrInitStartingStep.
func (s *memoryStore) GetOrInitStartingStep(
	startingStep int64,
) (int64, error) {
	if !s.startingStepInitialized {
		s.startingStep = startingStep
		s.startingStepInitialized = true
	}

	return s.startingStep, nil
}
