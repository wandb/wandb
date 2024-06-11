package filestream

// CollectorState is the filestream's buffered data.
type CollectorState struct {
	// Buffer is the next batch of data to send.
	Buffer TransmitChunk

	// ExitCode is the run's script's exit code if any.
	//
	// This is sent with the final transmission.
	ExitCode *int32

	// Complete is the run's script's completion status if any.
	//
	// This is sent with the final transmission.
	Complete *bool
}

func NewCollectorState(initialOffsets FileStreamOffsetMap) CollectorState {
	state := CollectorState{}

	if initialOffsets != nil {
		state.Buffer.HistoryLineNum = initialOffsets[HistoryChunk]
		state.Buffer.EventsLineNum = initialOffsets[EventsChunk]
		state.Buffer.ConsoleLogLineNum = initialOffsets[OutputChunk]
		state.Buffer.SummaryLineNum = initialOffsets[SummaryChunk]
	}

	return state
}

// CollectorStateUpdate is a mutation to a CollectorState.
type CollectorStateUpdate interface {
	// Apply modifies the collector state.
	Apply(*CollectorState)
}

// Consume turns the buffered data into an API request, resetting buffers.
//
// Returns a boolean that's true if the request is non-empty.
func (s *CollectorState) Consume(isDone bool) (*FsTransmitData, bool) {
	transmitData := FsTransmitData{}

	hasData := s.Buffer.FlushInto(&transmitData)
	if isDone {
		transmitData.Exitcode = s.ExitCode
		transmitData.Complete = s.Complete
		hasData = true
	}

	s.Buffer = TransmitChunk{}

	return &transmitData, hasData
}
