package filestream

import (
	"maps"
	"slices"

	"github.com/wandb/wandb/core/internal/sparselist"
)

// FileStreamRequest is data that can be sent via filestream.
//
// A key property of requests is that a sequence of requests can be
// compressed into a single request. This is realized via [Merge].
type FileStreamRequest struct {
	// HistoryLines is a list of lines to append to the run history.
	//
	// Each line is a JSON object mapping metric names to values.
	HistoryLines []string

	// EventsLines is a list of lines to append to the run's system metrics.
	//
	// Each line is a JSON object mapping metric names to values.
	EventsLines []string

	// LatestSummary is the run's most recent summary, JSON-encoded.
	LatestSummary string

	// ConsoleLines is updates to make to the run's output logs.
	//
	// Unlike history and system metrics, we often update past lines in
	// console logs due to terminal emulation. For example, this is how
	// tqdm-like progress bars work.
	ConsoleLines sparselist.SparseList[string]

	// UploadedFiles is a set of files that have been uploaded.
	//
	// This is used in deployments where the backend cannot detect when
	// a file registered with the run has been fully uploaded to whatever
	// storage system.
	UploadedFiles map[string]struct{}

	// Preempting is whether the script is about to yield the processor.
	//
	// This happens on certain machines where a run can be suspended
	// indefinitely to free up resources, but resumed later. During
	// this time, the run can't send any heartbeats to the backend,
	// so we send a preempting signal to tell it that the run isn't
	// dead and send more updates later.
	Preempting bool

	// Complete is whether the run has been marked as finished.
	Complete bool

	// ExitCode is the run's source script's exit code, if the run is complete.
	ExitCode int32
}

// Merge updates this request with the next request.
//
// The resulting request has the same effect as if this request was
// sent first, and the next request was sent after.
func (r *FileStreamRequest) Merge(next *FileStreamRequest) {
	r.HistoryLines = append(r.HistoryLines, next.HistoryLines...)
	r.EventsLines = append(r.EventsLines, next.EventsLines...)

	if next.LatestSummary != "" {
		r.LatestSummary = next.LatestSummary
	}

	r.ConsoleLines.Update(next.ConsoleLines)

	if r.UploadedFiles == nil {
		r.UploadedFiles = next.UploadedFiles
	} else {
		maps.Copy(r.UploadedFiles, next.UploadedFiles)
	}

	r.Preempting = r.Preempting || next.Preempting

	if next.Complete {
		r.Complete = next.Complete
		r.ExitCode = next.ExitCode
	}
}

// FileStreamRequestJSON is the actual JSON request we make to the API.
//
// A [FileStreamRequest] sometimes requires multiple JSON requests to
// represent it. This happens when non-consecutive runs of lines are
// updated in the console logs (only one run can be updated at a time
// due to the API's design), or to limit the request size.
//
// [FileStreamRequest] can be thought of as the "idealized" request;
// it is what we wish the API looked like.
type FileStreamRequestJSON struct {
	Files      map[string]offsetAndContent `json:"files,omitempty"`
	Uploaded   []string                    `json:"uploaded,omitempty"`
	Preempting *bool                       `json:"preempting,omitempty"`

	Complete *bool  `json:"complete,omitempty"`
	ExitCode *int32 `json:"exitcode,omitempty"`
}

// offsetAndContent is a run of lines to update in a filestream file.
type offsetAndContent struct {
	Offset  int      `json:"offset"`
	Content []string `json:"content"`
}

// FileStreamRequestReader breaks an abstracted [FileStreamRequest] into
// multiple [fileStreamRequestJSON] values.
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
	isAtMaxSize := false

	// Increases requestSizeApprox and returns the number of strings to
	// send from the list.
	addStringsToRequest := func(data []string) int {
		for i, line := range data {
			nextSize := requestSizeApprox + len(line)

			if nextSize > requestSizeLimitBytes {
				isAtMaxSize = true

				// As a special case, if the first line is larger than the limit
				// and we're not sending any other data, send the line and hope
				// it goes through.
				if requestSizeApprox == 0 && i == 0 {
					requestSizeApprox = nextSize
					return 1
				} else {
					return i
				}
			}

			requestSizeApprox = nextSize
		}

		return len(data)
	}

	// We always send the summary.
	requestSizeApprox += len(request.LatestSummary)

	historyLinesToSend := addStringsToRequest(request.HistoryLines)
	eventsLinesToSend := addStringsToRequest(request.EventsLines)

	consoleLineRuns := request.ConsoleLines.ToRuns()
	consoleLinesToSend := 0
	if len(consoleLineRuns) > 0 {
		consoleLinesToSend = addStringsToRequest(consoleLineRuns[0].Items)
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

	// isAtMaxSize is different from isFullRequest: a request could be partial
	// but still below the size limit if it contains nonconsecutive console
	// lines.
	return reader, isAtMaxSize
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

// GetJSON returns the first JSON request from the sequence represented
// by the underlying [FileStreamRequest] and updates the [fileStreamState].
func (r *FileStreamRequestReader) GetJSON(
	state *FileStreamState,
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
	if r.request.LatestSummary != "" {
		json.Files[SummaryFileName] = offsetAndContent{
			Offset:  state.SummaryLineNum,
			Content: []string{r.request.LatestSummary},
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
