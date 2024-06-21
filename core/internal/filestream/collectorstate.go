package filestream

import (
	"slices"

	"github.com/wandb/wandb/core/internal/sparselist"
)

// CollectorState is the filestream's buffered data.
type CollectorState struct {
	HistoryLineNum int      // Line number where to append run history.
	HistoryLines   []string // Lines to append to run history.

	EventsLineNum int      // Line number where to append run system metrics.
	EventsLines   []string // Lines to append to run system metrics.

	// Lines to update in the run's console logs file.
	ConsoleLogUpdates sparselist.SparseList[string]

	// Offset to add to all console output line numbers.
	//
	// This is used for resumed runs, where we want to append to the original
	// logs.
	ConsoleLogLineOffset int

	SummaryLineNum int    // Line number where to write the run summary.
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
		state.ConsoleLogLineOffset = initialOffsets[OutputChunk]
		state.SummaryLineNum = initialOffsets[SummaryChunk]
	}

	return state
}

// CollectorStateUpdate is a mutation to a CollectorState.
type CollectorStateUpdate interface {
	// Apply modifies the collector state.
	Apply(*CollectorState)
}

// PrepRequest prepares an API request from the collected data.
//
// After this, the state must not be modified until either:
//
//   - The return value is discarded
//   - `RequestSent` is invoked
func (s *CollectorState) PrepRequest(isDone bool) *FsTransmitData {
	files := make(map[string]FsTransmitFileData)

	if len(s.HistoryLines) > 0 {
		files[chunkFilename[HistoryChunk]] = FsTransmitFileData{
			Offset:  s.HistoryLineNum,
			Content: s.HistoryLines,
		}
	}

	if len(s.EventsLines) > 0 {
		files[chunkFilename[EventsChunk]] = FsTransmitFileData{
			Offset:  s.EventsLineNum,
			Content: s.EventsLines,
		}
	}

	if s.ConsoleLogUpdates.Len() > 0 {
		// We can only upload one run of lines at a time, unfortunately.
		run := s.ConsoleLogUpdates.ToRuns()[0]
		files[chunkFilename[OutputChunk]] = FsTransmitFileData{
			Offset:  run.Start + s.ConsoleLogLineOffset,
			Content: run.Items,
		}
	}

	if s.LatestSummary != "" {
		// We always write to the same line in the summary file.
		//
		// The reason this isn't always line 0 is for compatibility with old
		// runs where we appended to the summary file. In that case, we want
		// to update the last line, since all other lines are ignored. This
		// applies to resumed runs.
		files[chunkFilename[SummaryChunk]] = FsTransmitFileData{
			Offset:  s.SummaryLineNum,
			Content: []string{s.LatestSummary},
		}
	}

	transmitData := FsTransmitData{}

	if len(files) > 0 {
		transmitData.Files = files
	}

	if len(s.UploadedFiles) > 0 {
		transmitData.Uploaded = slices.Clone(s.UploadedFiles)
	}

	if s.HasPreempting {
		transmitData.Preempting = s.Preempting
	}

	if isDone {
		transmitData.Exitcode = s.ExitCode
		transmitData.Complete = s.Complete
	}

	return &transmitData
}

// RequestSent indicates that the result of PrepRequest was used.
func (s *CollectorState) RequestSent() {
	s.HistoryLineNum += len(s.HistoryLines)
	s.HistoryLines = nil

	s.EventsLineNum += len(s.EventsLines)
	s.EventsLines = nil

	// Drop uploaded lines.
	if s.ConsoleLogUpdates.Len() > 0 {
		run := s.ConsoleLogUpdates.ToRuns()[0]
		for i := run.Start; i < run.Start+len(run.Items); i++ {
			s.ConsoleLogUpdates.Delete(i)
		}
	}

	s.LatestSummary = ""

	s.UploadedFiles = nil

	s.HasPreempting = false
}
