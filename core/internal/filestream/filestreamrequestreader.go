package filestream

import (
	"slices"

	"github.com/wandb/wandb/core/internal/sparselist"
)

// FileStreamRequestReader breaks an abstracted [FileStreamRequest] into
// multiple [FileStreamRequestJSON] values.
type FileStreamRequestReader struct {
	// request is the source from which to consume data.
	//
	// NOTE: The request must not be modified!
	request *FileStreamRequest

	// selected is the part of the request the reader would consume.
	selected readerRequestPortion

	// isFullRequest is whether the entire `request` is `selected`.
	isFullRequest bool
}

type readerRequestPortion struct {
	// approxRequestSize is the estimated size in bytes of the request
	// the reader will produce, and maxRequestSize is its limit.
	approxRequestSize, maxRequestSize int

	// isTruncatedDueToSize is true if some portion of the request was
	// not selected because it would have exceeded the request size limit.
	isTruncatedDueToSize bool

	sendSummary        bool // whether to upload the summary
	historyLinesToSend int  // how many history lines to consume
	eventsLinesToSend  int  // how many events lines to consume

	// consoleLineRuns is consecutive runs of console lines.
	//
	// The first run is sent; the rest are kept for the next request.
	consoleLineRuns    []sparselist.Run[string]
	consoleLinesToSend int // how many lines to send from consoleLineRuns[0]
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

	// ConsoleLineOffset is an offset to add to all console updates.
	//
	// This is used when resuming a run, in which case we want the new
	// console logs to be appended to the old ones.
	ConsoleLineOffset int
}

// NewRequestReader makes a request reader and computes the request's size.
//
// The reader takes ownership of the request. Ownership is returned
// to the caller if the reader is discarded; otherwise, the caller
// must call [Next] to get the updated request (minus the data that
// was consumed).
//
// requestSizeLimitBytes is an approximate limit to the amount of
// data to include in the JSON request.
func NewRequestReader(
	request *FileStreamRequest,
	requestSizeLimitBytes int,
) *FileStreamRequestReader {
	reader := &FileStreamRequestReader{request: request}
	reader.selected.maxRequestSize = requestSizeLimitBytes

	reader.isFullRequest =
		reader.selected.tryAddSummary(request.LatestSummary) &&
			reader.selected.tryAddHistoryLines(request.HistoryLines) &&
			reader.selected.tryAddEventsLines(request.EventsLines) &&
			reader.selected.tryAddConsoleLines(request.ConsoleLines)

	return reader
}

// IsAtMaxSize returns true if the request is at the maximum size.
func (r *FileStreamRequestReader) IsAtMaxSize() bool {
	return r.selected.isTruncatedDueToSize ||
		// approxRequestSize is the size of the *selected* portion of
		// the request, which is usually below the max size except when
		// the request cannot be broken into small enough pieces.
		r.selected.approxRequestSize >= r.selected.maxRequestSize
}

// tryAddSummary adds the run summary to the request and returns
// whether it was added.
func (r *readerRequestPortion) tryAddSummary(line string) bool {
	if r.approxRequestSize > 0 &&
		r.approxRequestSize+len(line) > r.maxRequestSize {
		r.isTruncatedDueToSize = true
		return false
	}

	r.approxRequestSize += len(line)
	r.sendSummary = true
	return true
}

// tryAddHistoryLines adds history lines to the request and returns
// whether all of them were added.
func (r *readerRequestPortion) tryAddHistoryLines(lines []string) bool {
	for _, line := range lines {
		if r.approxRequestSize > 0 &&
			r.approxRequestSize+len(line) > r.maxRequestSize {
			r.isTruncatedDueToSize = true
			return false
		}

		r.approxRequestSize += len(line)
		r.historyLinesToSend++
	}

	return true
}

// tryAddEventsLines adds system metrics to the request and returns
// whether all lines were added.
func (r *readerRequestPortion) tryAddEventsLines(lines []string) bool {
	for _, line := range lines {
		if r.approxRequestSize > 0 &&
			r.approxRequestSize+len(line) > r.maxRequestSize {
			r.isTruncatedDueToSize = true
			return false
		}

		r.approxRequestSize += len(line)
		r.eventsLinesToSend++
	}

	return true
}

// tryAddConsoleLines adds console updates to the request and returns whether
// all of them were added.
func (r *readerRequestPortion) tryAddConsoleLines(
	lines sparselist.SparseList[string],
) bool {
	r.consoleLineRuns = lines.ToRuns()
	if len(r.consoleLineRuns) == 0 {
		return true
	}

	for _, line := range r.consoleLineRuns[0].Items {
		if r.approxRequestSize > 0 &&
			r.approxRequestSize+len(line) > r.maxRequestSize {
			r.isTruncatedDueToSize = true
			return false
		}

		r.approxRequestSize += len(line)
		r.consoleLinesToSend++
	}

	return len(r.consoleLineRuns) == 1
}

// GetJSON returns the first JSON request from the sequence represented
// by the underlying [FileStreamRequest] and updates the [fileStreamState].
func (r *FileStreamRequestReader) GetJSON(
	state *FileStreamState,
) *FileStreamRequestJSON {
	json := &FileStreamRequestJSON{
		Files: map[string]offsetAndContent{},
	}

	if r.selected.sendSummary && r.request.LatestSummary != "" {
		json.Files[SummaryFileName] = offsetAndContent{
			Offset:  state.SummaryLineNum,
			Content: []string{r.request.LatestSummary},
		}
	}
	if n := r.selected.historyLinesToSend; n > 0 {
		json.Files[HistoryFileName] = offsetAndContent{
			Offset:  state.HistoryLineNum,
			Content: r.request.HistoryLines[:n],
		}
		state.HistoryLineNum += n
	}
	if n := r.selected.eventsLinesToSend; n > 0 {
		json.Files[EventsFileName] = offsetAndContent{
			Offset:  state.EventsLineNum,
			Content: r.request.EventsLines[:n],
		}
		state.EventsLineNum += n
	}
	if n := r.selected.consoleLinesToSend; n > 0 {
		run := r.selected.consoleLineRuns[0]
		json.Files[OutputFileName] = offsetAndContent{
			Offset:  state.ConsoleLineOffset + run.Start,
			Content: run.Items[:n],
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
			r.request.HistoryLines[r.selected.historyLinesToSend:]),
		EventsLines: slices.Clone(
			r.request.EventsLines[r.selected.eventsLinesToSend:]),
	}

	if len(r.selected.consoleLineRuns) > 0 {
		// All unsent lines from the first block.
		run0 := r.selected.consoleLineRuns[0]
		for i := r.selected.consoleLinesToSend; i < len(run0.Items); i++ {
			next.ConsoleLines.Put(run0.Start+i, run0.Items[i])
		}

		// All other unsent blocks.
		for _, run := range r.selected.consoleLineRuns[1:] {
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
