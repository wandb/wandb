package filestream

import (
	"fmt"
	"maps"
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsummary"
)

// FileStreamState turns a [FileStreamRequest] into sequence
// of [FileStreamRequestJSON].
type FileStreamState struct {
	// MaxRequestSizeBytes is an approximate maximum FileStream request size
	// in bytes.
	MaxRequestSizeBytes int

	// MaxFileLineSize is an approximate maximum per-line size in bytes for
	// the "Files" uploaded in FileStream.
	MaxFileLineSize int

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

	// RunSummary is the run's full summary.
	//
	// It may be nil if the run has no summary.
	RunSummary *runsummary.RunSummary

	// LastRunSummarySize is the size in bytes of the last serialized summary,
	// used to estimate the size of the next one.
	LastRunSummarySize int

	// SummaryDelta is whether the backend accepts summary deltas
	// for this stream.
	SummaryDelta bool

	// ConsoleLineOffset is an offset to add to all console updates.
	//
	// This is used when resuming a run, in which case we want the new
	// console logs to be appended to the old ones.
	ConsoleLineOffset int
}

// IsAtSizeLimit returns true if the next JSON chunk of the request could
// contain more than around maxBytes of data.
func (s *FileStreamState) IsAtSizeLimit(request *FileStreamRequest) bool {
	approxSize := 0

	for _, line := range request.HistoryLines {
		approxSize += len(line)
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	for _, line := range request.EventsLines {
		approxSize += len(line)
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	// Use the last summary size to approximate the next.
	// It is too expensive to serialize the summary every time and too complex
	// to track its size incrementally.
	if !request.SummaryUpdates.IsEmpty() {
		approxSize += s.LastRunSummarySize
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	for line := range request.ConsoleLines.FirstRunValues() {
		approxSize += len(line)
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	return false
}

// Pop extracts a chunk of data from the request, limiting its JSON
// representation to approximately the maximum size.
//
// The second return value is true if there remains unsent data in the request.
func (s *FileStreamState) Pop(
	request *FileStreamRequest,
	logger *observability.CoreLogger,
	printer *observability.Printer,
) (*FileStreamRequestJSON, bool) {
	builder := &requestJSONBuilder{}
	builder.MaxSizeBytes = s.MaxRequestSizeBytes

	s.popHistory(builder, request)
	s.popEvents(builder, request)
	s.popSummary(builder, request, logger, printer)
	s.popConsoleLines(builder, request)

	s.popUploadedFiles(builder, request)
	s.popPreempting(builder, request)

	if !builder.HasMore && request.Complete {
		builder.Complete = true
		builder.ExitCode = request.ExitCode
	}

	return builder.Build(), builder.HasMore
}

func (s *FileStreamState) popHistory(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	poppedLines := false
	defer func() {
		if poppedLines {
			// Free unused memory.
			request.HistoryLines = slices.Clone(request.HistoryLines)
		}
	}()

	builder.HistoryChunk.Offset = s.HistoryLineNum

	for len(request.HistoryLines) > 0 {
		line := request.HistoryLines[0]

		if !builder.TryAddSize(len(line)) {
			builder.HasMore = true
			return
		}

		poppedLines = true
		builder.HistoryChunk.Content = append(builder.HistoryChunk.Content, line)
		request.HistoryLines = request.HistoryLines[1:]
		s.HistoryLineNum++
	}
}

func (s *FileStreamState) popEvents(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	poppedLines := false
	defer func() {
		if poppedLines {
			// Free unused memory.
			request.EventsLines = slices.Clone(request.EventsLines)
		}
	}()

	builder.EventsChunk.Offset = s.EventsLineNum

	for len(request.EventsLines) > 0 {
		line := request.EventsLines[0]

		if !builder.TryAddSize(len(line)) {
			builder.HasMore = true
			return
		}

		poppedLines = true
		builder.EventsChunk.Content = append(builder.EventsChunk.Content, line)
		request.EventsLines = request.EventsLines[1:]
		s.EventsLineNum++
	}
}

// popSummary adds the summary to the request if it changed.
//
// Summary updates stay in the request until a summary is sent, so they are
// the changes since the last summary sent. If the backend accepts deltas,
// they are sent without values from history, which the backend takes from
// the history it receives. The full summary is sent instead:
//   - for changes that remove a key, which a delta can't express
//   - at the end of the stream, changed or not, so that the backend ends up
//     with every value
func (s *FileStreamState) popSummary(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
	logger *observability.CoreLogger,
	printer *observability.Printer,
) {
	final := s.SummaryDelta && request.Complete && !builder.HasMore
	if request.SummaryUpdates.IsEmpty() && (!final || s.RunSummary == nil) {
		return
	}

	asDelta := s.SummaryDelta && !final &&
		!request.SummaryUpdates.HasRemovals()
	summaryJSON, err := s.serializeSummary(request.SummaryUpdates, asDelta, logger)
	switch {
	case err != nil:
		logger.CaptureError(
			"filestream",
			fmt.Errorf("filestream: failed to serialize summary: %v", err),
		)
		request.SummaryUpdates = nil
		return

	case asDelta && string(summaryJSON) == "{}":
		// Every change is a value from history, or a None.
		request.SummaryUpdates = nil
		return
	}

	s.LastRunSummarySize = len(summaryJSON)

	if len(summaryJSON) > s.MaxFileLineSize {
		logger.Warn(
			"filestream: run summary line too long, skipping",
			"len", len(summaryJSON),
			"max", s.MaxFileLineSize,
		)
		printer.
			AtMostEvery(time.Minute).
			Warnf(
				"Skipped uploading summary data that exceeded"+
					" size limit (%d > %d bytes).",
				len(summaryJSON),
				s.MaxFileLineSize,
			)

		// Drop the summary. Later changes are sent as usual.
		request.SummaryUpdates = nil
		return
	}

	if !builder.TryAddSize(len(summaryJSON)) {
		// The updates stay in the request and merge with later changes.
		builder.HasMore = true
		return
	}

	builder.SummaryChunk.Offset = s.SummaryLineNum
	builder.SummaryChunk.Content = []string{string(summaryJSON)}
	builder.SummaryDelta = asDelta
	request.SummaryUpdates = nil
}

// serializeSummary applies the updates to RunSummary and returns the updates
// without values from history if asDelta is true, or else the full summary.
func (s *FileStreamState) serializeSummary(
	updates *runsummary.Updates,
	asDelta bool,
	logger *observability.CoreLogger,
) ([]byte, error) {
	if s.RunSummary == nil {
		s.RunSummary = runsummary.New()
	}

	// Updates that didn't fit in an earlier request were applied then.
	// Applying them again has no further effect.
	if err := updates.Apply(s.RunSummary); err != nil {
		// A partial success is possible, so we log and continue.
		logger.CaptureError(
			"filestream",
			fmt.Errorf("filestream: error applying summary updates: %v", err),
		)
	}

	if asDelta {
		return updates.SerializeWithoutHistory()
	}
	return s.RunSummary.Serialize()
}

func (s *FileStreamState) popConsoleLines(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	builder.ConsoleLinesChunk.Offset =
		s.ConsoleLineOffset + request.ConsoleLines.FirstIndex()

	for idx, line := range request.ConsoleLines.FirstRun() {
		if !builder.TryAddSize(len(line)) {
			builder.HasMore = true
			return
		}

		builder.ConsoleLinesChunk.Content = append(
			builder.ConsoleLinesChunk.Content,
			line,
		)
		request.ConsoleLines.Delete(idx)
	}

	// We can only upload one consecutive run of console lines at a time.
	if request.ConsoleLines.Len() > 0 {
		builder.HasMore = true
	}
}

func (s *FileStreamState) popUploadedFiles(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	builder.Uploaded = slices.Collect(maps.Keys(request.UploadedFiles))
	request.UploadedFiles = nil
}

func (s *FileStreamState) popPreempting(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	builder.Preempting = request.Preempting
	request.Preempting = false
}

// requestJSONBuilder builds a [FileStreamRequestJSON].
type requestJSONBuilder struct {
	ApproxSizeBytes, MaxSizeBytes int
	HasMore                       bool

	HistoryChunk      OffsetAndContent
	EventsChunk       OffsetAndContent
	SummaryChunk      OffsetAndContent
	ConsoleLinesChunk OffsetAndContent

	Uploaded     []string
	Preempting   bool
	SummaryDelta bool

	Complete bool
	ExitCode int32 // only sent if Complete
}

// TryAddSize returns whether n more bytes can be added to the request
// and updates the request size if so.
func (b *requestJSONBuilder) TryAddSize(n int) bool {
	newSize := b.ApproxSizeBytes + n

	if b.ApproxSizeBytes == 0 || newSize <= b.MaxSizeBytes {
		b.ApproxSizeBytes = newSize
		return true
	} else {
		return false
	}
}

// Build returns the JSON value to upload.
func (x *requestJSONBuilder) Build() *FileStreamRequestJSON {
	json := &FileStreamRequestJSON{}
	json.Files = make(map[string]OffsetAndContent)

	if len(x.HistoryChunk.Content) > 0 {
		json.Files[HistoryFileName] = x.HistoryChunk
	}
	if len(x.EventsChunk.Content) > 0 {
		json.Files[EventsFileName] = x.EventsChunk
	}
	if len(x.SummaryChunk.Content) > 0 {
		json.Files[SummaryFileName] = x.SummaryChunk
		json.SummaryDelta = nullify.NilIfZero(x.SummaryDelta)
	}
	if len(x.ConsoleLinesChunk.Content) > 0 {
		json.Files[OutputFileName] = x.ConsoleLinesChunk
	}

	json.Uploaded = x.Uploaded
	json.Preempting = nullify.NilIfZero(x.Preempting)

	if x.Complete {
		complete := x.Complete
		json.Complete = &complete

		exitCode := x.ExitCode
		json.ExitCode = &exitCode
	}

	return json
}
