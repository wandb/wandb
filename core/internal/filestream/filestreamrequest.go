package filestream

import "github.com/wandb/wandb/core/internal/sparselist"

// FileStreamRequest is the request format expected by the filestream API.
type FileStreamRequest struct {
	// Files contains line-by-line updates to "files" like
	// "wandb-history.jsonl" or "output.log".
	Files map[string]FileStreamFileData `json:"files,omitempty"`

	// Uploaded is a list of run files that were successfully uploaded.
	//
	// This is used in deployments where run files are stored separately
	// and it's unknown whether
	Uploaded []string `json:"uploaded,omitempty"`

	// Preempting indicates that the run process is about to yield access
	// to the CPU for a potentially long duration.
	//
	// This informs the backend not to consider the run as crashed if it
	// doesn't send updates for some time.
	Preempting *bool `json:"preempting,omitempty"`

	// Complete is whether the run finished.
	//
	// This indicates to the backend that the W&B process completed uploading
	// all necessary data. It must only be sent with the last transmission.
	Complete *bool `json:"complete,omitempty"`

	// ExitCode is the exit code of the run's script.
	//
	// It must only be sent with the last transmission.
	ExitCode *int32 `json:"exitcode,omitempty"`

	// TODO: add FileStreamRequest.Dropped?
}

type FileStreamFileData struct {
	// Offset is the line number of the first line to add or overwrite.
	Offset int `json:"offset"`

	// Content is the new lines to write to the file.
	//
	// The lines shouldn't include '\n' characters.
	Content []string `json:"content"`
}

// FileStreamRequestBuffer accumulates FS requests.
type FileStreamRequestBuffer struct {
	// finalized is true when filestream is done accumulating updates.
	finalized bool

	HistoryLineNum int
	HistoryLines   []string

	EventsLineNum int
	EventsLines   []string

	SummaryLineNum int
	LatestSummary  string

	// Lines to update in the run's console logs file.
	ConsoleLogUpdates sparselist.SparseList[string]

	// Offset to add to all console output line numbers.
	//
	// This is used for resumed runs, where we want to append to the original
	// logs.
	ConsoleLogLineOffset int

	// UploadedFiles are files for which uploads have finished.
	UploadedFiles []string

	ExitCode   *int32
	Complete   *bool
	Preempting *bool
}

// Finalize indicates that there are no more updates to accumulate.
//
// After this, Get() and Advance() should be called until all remaining
// data is consumed.
func (b *FileStreamRequestBuffer) Finalize() {
	b.finalized = true
}

// Get returns the next FileStreamRequest to send.
//
// This returns three values:
//
//   - The request to make
//   - Whether this is the final request to make
//   - An "advancer" to produce the buffer's next value
//
// If the request is used, then the buffer must not be modified
// and advancer.Advance() must be used to get the next buffer value.
func (b *FileStreamRequestBuffer) Get() (
	*FileStreamRequest,
	bool,
	*fileStreamBufferAdvancer,
) {
	req := &FileStreamRequest{
		Files:      make(map[string]FileStreamFileData),
		Uploaded:   b.UploadedFiles,
		Preempting: b.Preempting,
	}
	advancer := &fileStreamBufferAdvancer{prev: b}
	hasMoreDataAfter := false

	if len(b.HistoryLines) > 0 {
		req.Files[HistoryFileName] = FileStreamFileData{
			Offset:  b.HistoryLineNum,
			Content: b.HistoryLines,
		}
	}

	if len(b.EventsLines) > 0 {
		req.Files[EventsFileName] = FileStreamFileData{
			Offset:  b.EventsLineNum,
			Content: b.EventsLines,
		}
	}

	if b.ConsoleLogUpdates.Len() > 0 {
		// We can only upload one run of lines at a time, unfortunately.
		runs := b.ConsoleLogUpdates.ToRuns()
		run := runs[0]
		req.Files[OutputFileName] = FileStreamFileData{
			Offset:  run.Start + b.ConsoleLogLineOffset,
			Content: run.Items,
		}

		if len(runs) > 1 {
			hasMoreDataAfter = true
			advancer.remainingOutputLines = runs[1:]
		}
	}

	if b.LatestSummary != "" {
		// We always write to the same line in the summary file.
		//
		// The reason this isn't always line 0 is for compatibility with old
		// runs where we appended to the summary file. In that case, we want
		// to update the last line, since all other lines are ignored. This
		// applies to resumed runs.
		req.Files[SummaryFileName] = FileStreamFileData{
			Offset:  b.SummaryLineNum,
			Content: []string{b.LatestSummary},
		}
	}

	// On the final request, mark the run complete and send the exit code.
	isFinalRequest := b.finalized && !hasMoreDataAfter
	if isFinalRequest {
		req.Complete = b.Complete
		req.ExitCode = b.ExitCode
	}

	return req, isFinalRequest, advancer
}

// fileStreamBufferAdvancer produces the next value of the buffer.
type fileStreamBufferAdvancer struct {
	prev                 *FileStreamRequestBuffer
	remainingOutputLines []sparselist.Run[string]
}

// Advance returns an updated buffer minus the request returned by Get().
func (b *fileStreamBufferAdvancer) Advance() *FileStreamRequestBuffer {
	outputLines := sparselist.SparseList[string]{}
	for _, run := range b.remainingOutputLines {
		for i, line := range run.Items {
			outputLines.Put(run.Start+i, line)
		}
	}

	return &FileStreamRequestBuffer{
		finalized: b.prev.finalized,

		HistoryLineNum: b.prev.HistoryLineNum + len(b.prev.HistoryLines),
		EventsLineNum:  b.prev.EventsLineNum + len(b.prev.EventsLines),
		SummaryLineNum: b.prev.SummaryLineNum,

		ConsoleLogUpdates:    outputLines,
		ConsoleLogLineOffset: b.prev.ConsoleLogLineOffset,

		ExitCode: b.prev.ExitCode,
		Complete: b.prev.Complete,
	}
}
