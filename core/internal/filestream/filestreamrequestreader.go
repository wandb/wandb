package filestream

import (
	"fmt"
	"slices"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// FileStreamRequestReader breaks an abstracted [FileStreamRequest] into
// multiple [FileStreamRequestJSON] values.
type FileStreamRequestReader struct {
	// request is the source from which to consume data.
	//
	// NOTE: The request must not be modified!
	request *FileStreamRequest

	historyLinesToSend int // how many history lines to consume
	eventsLinesToSend  int // how many events lines to consume

	// consoleLineRuns is consecutive runs of console lines.
	//
	// The first run is sent; the rest are kept for the next request.
	consoleLineRuns    []sparselist.Run[string]
	consoleLinesToSend int // how many lines to send from consoleLineRuns[0]

	// isFullRequest is whether the entire [FileStreamRequest] can
	// be represented by a single JSON request.
	isFullRequest bool
}

// FileStreamState is state necessary to turn a [FileStreamRequest]
// into sequence of JSON requests.
type FileStreamState struct {
	// HistoryLineNum is the line number where to append history.
	HistoryLineNum int

	// EventsLineNum is the line number where to append system metrics.
	EventsLineNum int

	// SummaryLineNum is the line number where to write the summary.
	//
	// The same line is always overwritten. The reason we don't solely
	// update line 0 is for compatibility with previous versions which
	// appended summaries. The backend only looks at the last line, so
	// to properly resume such a run we must update the last line.
	SummaryLineNum int

	// RunSummary is the run's entire summary.
	//
	// Due to backend limitations, we always send the full summary
	// to update it rather than sending incremental updates.
	RunSummary *runsummary.RunSummary

	// ConsoleLineOffset is an offset to add to all console updates.
	//
	// This is used when resuming a run, in which case we want the new
	// console logs to be appended to the old ones.
	ConsoleLineOffset int
}

func NewFileStreamState() *FileStreamState {
	return &FileStreamState{RunSummary: runsummary.New()}
}

// NewRequestReader makes a request reader and computes the request's size.
//
// The reader takes ownership of the request. Ownership is returned
// to the caller if the reader is discarded; otherwise, the caller
// must call [Next] to get the updated request (minus the data that
// was consumed).
//
// requestSizeLimitBytes is an approximate limit to the amount of
// data to include in the JSON request. The second return value
// indicates whether the request would be truncated to fit this.
func NewRequestReader(
	request *FileStreamRequest,
	requestSizeLimitBytes int,
) (*FileStreamRequestReader, bool) {
	requestSizeApprox := 0
	isTruncatedDueToSize := false

	// Increases requestSizeApprox and returns the number of strings to
	// send from the list.
	addStringsToRequest := func(data ...string) int {
		for i, line := range data {
			nextSize := requestSizeApprox + len(line)

			if nextSize <= requestSizeLimitBytes {
				requestSizeApprox = nextSize
				continue
			}

			isTruncatedDueToSize = true

			// As a special case, if the first line is larger than the limit
			// and we're not sending any other data, send the line and hope
			// it goes through.
			if requestSizeApprox == 0 {
				requestSizeApprox = nextSize
				return 1
			} else {
				return i
			}
		}

		return len(data)
	}

	// TODO: Add summary size.
	historyLinesToSend := addStringsToRequest(request.HistoryLines...)
	eventsLinesToSend := addStringsToRequest(request.EventsLines...)

	consoleLineRuns := request.ConsoleLines.ToRuns()
	consoleLinesToSend := 0
	if len(consoleLineRuns) > 0 {
		consoleLinesToSend = addStringsToRequest(consoleLineRuns[0].Items...)
	}

	reader := &FileStreamRequestReader{
		request:            request,
		historyLinesToSend: historyLinesToSend,
		eventsLinesToSend:  eventsLinesToSend,

		consoleLineRuns:    consoleLineRuns,
		consoleLinesToSend: consoleLinesToSend,
	}

	switch {
	case historyLinesToSend != len(request.HistoryLines):
		reader.isFullRequest = false
	case eventsLinesToSend != len(request.EventsLines):
		reader.isFullRequest = false
	case len(consoleLineRuns) > 1:
		reader.isFullRequest = false
	case len(consoleLineRuns) == 1 && consoleLinesToSend != len(consoleLineRuns[0].Items):
		reader.isFullRequest = false

	default:
		reader.isFullRequest = true
	}

	// isTruncatedDueToSize is different from isFullRequest: a request could be
	// partial if it contains nonconsecutive console lines.
	return reader, isTruncatedDueToSize
}

// GetJSON returns the first JSON request from the sequence represented
// by the underlying [FileStreamRequest] and updates the [fileStreamState].
func (r *FileStreamRequestReader) GetJSON(
	state *FileStreamState,
	logger *observability.CoreLogger,
) *FileStreamRequestJSON {
	json := &FileStreamRequestJSON{
		Files: map[string]offsetAndContent{},
	}

	if r.historyLinesToSend > 0 {
		json.Files[HistoryFileName] = offsetAndContent{
			Offset:  state.HistoryLineNum,
			Content: r.request.HistoryLines[:r.historyLinesToSend],
		}
		state.HistoryLineNum += r.historyLinesToSend
	}
	if r.eventsLinesToSend > 0 {
		json.Files[EventsFileName] = offsetAndContent{
			Offset:  state.EventsLineNum,
			Content: r.request.EventsLines[:r.eventsLinesToSend],
		}
		state.EventsLineNum += r.eventsLinesToSend
	}
	if !r.request.SummaryUpdates.IsEmpty() {
		err := r.request.SummaryUpdates.Apply(state.RunSummary)

		// A partial success is possible, so we continue after logging.
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("filestream: error applying summary updates: %v", err))
		}

		summaryJSON, err := state.RunSummary.Serialize()
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("filestream: failed to serialize summary: %v", err))
		} else {
			json.Files[SummaryFileName] = offsetAndContent{
				Offset:  state.SummaryLineNum,
				Content: []string{string(summaryJSON)},
			}
		}
	}
	if len(r.consoleLineRuns) > 0 {
		run := r.consoleLineRuns[0]
		json.Files[OutputFileName] = offsetAndContent{
			Offset:  state.ConsoleLineOffset + run.Start,
			Content: run.Items[:r.consoleLinesToSend],
		}
	}

	json.Uploaded = make([]string, 0, len(r.request.UploadedFiles))
	for file := range r.request.UploadedFiles {
		json.Uploaded = append(json.Uploaded, file)
	}

	if r.request.Preempting {
		boolTrue := true
		json.Preempting = &boolTrue
	}

	if r.request.Complete && r.isFullRequest {
		boolTrue := true
		exitCode := r.request.ExitCode
		json.Complete = &boolTrue
		json.ExitCode = &exitCode
	}

	return json
}

// Next returns the request minus the data consumed in [GetJSON].
//
// The second return value indicates whether the entire request was consumed.
func (r *FileStreamRequestReader) Next() (*FileStreamRequest, bool) {
	next := &FileStreamRequest{
		HistoryLines: slices.Clone(
			r.request.HistoryLines[r.historyLinesToSend:]),
		EventsLines: slices.Clone(
			r.request.EventsLines[r.eventsLinesToSend:]),
	}

	if len(r.consoleLineRuns) > 0 {
		// All unsent lines from the first block.
		run0 := r.consoleLineRuns[0]
		for i := r.consoleLinesToSend; i < len(run0.Items); i++ {
			next.ConsoleLines.Put(run0.Start+i, run0.Items[i])
		}

		// All other unsent blocks.
		for _, run := range r.consoleLineRuns[1:] {
			for i, line := range run.Items {
				next.ConsoleLines.Put(run.Start+i, line)
			}
		}
	}

	if !r.isFullRequest {
		next.Complete = r.request.Complete
		next.ExitCode = r.request.ExitCode
	}

	return next, r.isFullRequest
}
