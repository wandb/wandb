package filestream

import (
	"maps"

	"github.com/wandb/wandb/core/internal/runsummary"
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

	// SummaryUpdates contains changes to the run's summary.
	SummaryUpdates *runsummary.Updates

	// ConsoleLines is updates to make to the run's output logs.
	//
	// Unlike history and system metrics, we often update past lines in
	// console logs due to terminal emulation. For example, this is how
	// tqdm-like progress bars work.
	ConsoleLines *sparselist.SparseList[string]

	// UploadedFiles is a set of files that have been uploaded.
	//
	// This is used in deployments where the backend cannot detect when
	// a file registered with the run has been fully uploaded to whatever
	// storage system.
	UploadedFiles map[string]struct{}

	// For Sweeps: Preempting is whether the script is about to yield the
	// processor.
	//
	// If set when Complete is false, marks the run as preempting, such
	// that it will get enqueued for next agent to claim if it later exits with
	// a non-zero exit code or times out.
	//
	// If set when Complete is true, indicates that backend should enqueue the
	// run now for the next agent to claim if the exit code is non-zero.
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

	if r.SummaryUpdates == nil {
		r.SummaryUpdates = next.SummaryUpdates
	} else {
		r.SummaryUpdates.Merge(next.SummaryUpdates)
	}

	if r.ConsoleLines == nil {
		r.ConsoleLines = next.ConsoleLines
	} else {
		r.ConsoleLines.Update(next.ConsoleLines)
	}

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
