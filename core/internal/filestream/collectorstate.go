package filestream

// CollectorState is the filestream's buffered data.
type CollectorState struct {
	HistoryLineNum int      // Line number where to append run history.
	HistoryLines   []string // Lines to append to run history.

	EventsLineNum int      // Line number where to append run system metrics.
	EventsLines   []string // Lines to append to run system metrics.

	ConsoleLogLineNum int      // Line number where to append console output.
	ConsoleLogLines   []string // Lines to append to console output.

	SummaryLineNum int    // Line number where to append the run summary.
	LatestSummary  string // The run's updated summary, or the empty string.

	// UploadedFiles are files for which uploads have finished.
	UploadedFiles []string

	HasPreempting bool
	Preempting    bool

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
		state.HistoryLineNum = initialOffsets[HistoryChunk]
		state.EventsLineNum = initialOffsets[EventsChunk]
		state.ConsoleLogLineNum = initialOffsets[OutputChunk]
		state.SummaryLineNum = initialOffsets[SummaryChunk]
	}

	return state
}

// CollectorStateUpdate is a mutation to a CollectorState.
type CollectorStateUpdate interface {
	// Apply modifies the collector state.
	Apply(*CollectorState)
}

// MakeRequest moves buffered data into an API request and returns it.
//
// Returns a boolean that's true if the request is non-empty.
func (s *CollectorState) MakeRequest(isDone bool) (*FsTransmitData, bool) {
	files := make(map[string]FsTransmitFileData)
	addLines := func(chunkType ChunkTypeEnum, lineNum int, lines []string) {
		if len(lines) == 0 {
			return
		}
		files[chunkFilename[chunkType]] = FsTransmitFileData{
			Offset:  lineNum,
			Content: lines,
		}
	}

	addLines(HistoryChunk, s.HistoryLineNum, s.HistoryLines)
	s.HistoryLineNum += len(s.HistoryLines)
	s.HistoryLines = nil

	addLines(EventsChunk, s.EventsLineNum, s.EventsLines)
	s.EventsLineNum += len(s.EventsLines)
	s.EventsLines = nil

	addLines(OutputChunk, s.ConsoleLogLineNum, s.ConsoleLogLines)
	s.ConsoleLogLineNum += len(s.ConsoleLogLines)
	s.ConsoleLogLines = nil

	if s.LatestSummary != "" {
		addLines(SummaryChunk, s.SummaryLineNum, []string{s.LatestSummary})
		s.SummaryLineNum += 1
		s.LatestSummary = ""
	}

	transmitData := FsTransmitData{}
	hasData := false

	if len(files) > 0 {
		transmitData.Files = files
		hasData = true
	}

	if len(s.UploadedFiles) > 0 {
		transmitData.Uploaded = s.UploadedFiles
		s.UploadedFiles = nil
		hasData = true
	}

	if s.HasPreempting {
		transmitData.Preempting = s.Preempting
		hasData = true
	}

	if isDone {
		transmitData.Exitcode = s.ExitCode
		transmitData.Complete = s.Complete
		hasData = true
	}

	return &transmitData, hasData
}
